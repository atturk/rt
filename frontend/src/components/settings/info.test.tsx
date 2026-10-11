import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { api, type Schemas } from '@/api/client'
import { CacheSection, ChangelogSection, InfoSection } from './info'

const filled: Schemas['CacheInfo'] = {
  audio: { entries: 10, bytes: 2 * 1024 * 1024 },
  waveform: { entries: 2, bytes: 1024 * 1024 },
  total: { entries: 12, bytes: 3 * 1024 * 1024 },
}
const empty: Schemas['CacheInfo'] = {
  audio: { entries: 0, bytes: 0 }, waveform: { entries: 0, bytes: 0 }, total: { entries: 0, bytes: 0 },
}

function result(data: unknown) { return { data, response: new Response('{}', { status: 200 }) } }
function renderCache(data = filled, fullInfo = false) {
  let current = data
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(result(
    path === '/api/v1/system/cache' ? current : path === '/api/v1/system/changelog' ? [] : {},
  ))) as never)
  const remove = vi.spyOn(api, 'DELETE').mockImplementation((() => {
    current = empty
    return Promise.resolve(result(data))
  }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}>{fullInfo ? <InfoSection /> : <CacheSection />}</QueryClientProvider>)
  return remove
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Spazio e cache', () => {
  it('compare nelle informazioni con dimensioni e conteggi', async () => {
    renderCache(filled, true)
    const section = screen.getByRole('region', { name: 'Spazio e cache' })
    expect(await within(section).findByText('2.0 MB · 10 file')).toBeVisible()
    expect(within(section).getByText('1.0 MB · 2 file')).toBeVisible()
    expect(within(section).getByText('3.0 MB')).toBeVisible()
  })

  it('chiede conferma e non cancella quando si annulla', async () => {
    const remove = renderCache()
    const button = screen.getByRole('button', { name: 'Svuota la cache' })
    await waitFor(() => expect(button).toBeEnabled())
    await userEvent.click(button)
    const dialog = screen.getByRole('dialog', { name: 'Svuota la cache' })
    expect(within(dialog).getByText('Svuotare la cache (3.0 MB)?')).toBeVisible()
    expect(remove).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(remove).not.toHaveBeenCalled()
  })

  it('alla conferma chiama DELETE e aggiorna dimensione e spazio liberato', async () => {
    const remove = renderCache()
    const button = screen.getByRole('button', { name: 'Svuota la cache' })
    await waitFor(() => expect(button).toBeEnabled())
    await userEvent.click(button)
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Svuota' }))
    await waitFor(() => expect(remove).toHaveBeenCalledExactlyOnceWith('/api/v1/system/cache'))
    expect(await screen.findByRole('status')).toHaveTextContent('Liberati 3.0 MB.')
    await waitFor(() => expect(button).toBeDisabled())
    expect(screen.getByText('0 B')).toBeVisible()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('con cache vuota mostra zero e disabilita lo svuotamento', async () => {
    renderCache(empty)
    expect(await screen.findByText('0 B')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Svuota la cache' })).toBeDisabled()
  })

  it('se DELETE fallisce tiene aperta la conferma e mostra l’errore', async () => {
    const remove = renderCache()
    remove.mockResolvedValue({ error: { error: { code: 'cache_error', message: 'Cache non svuotata.' } },
      response: new Response('{}', { status: 500 }) } as never)
    const button = screen.getByRole('button', { name: 'Svuota la cache' })
    await waitFor(() => expect(button).toBeEnabled())
    await userEvent.click(button)
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Svuota' }))
    expect(await within(dialog).findByText('Cache non svuotata.')).toBeVisible()
    expect(dialog).toBeVisible()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})


it('Novità apre la versione installata, lascia chiuse le precedenti e mostra testo semplice', async () => {
  const sections = [{ version: '4.2.4b1', date: '2026-10-09', groups: [{ title: 'Novità', items: ['Zen.', '<b>Testo semplice</b>'] }] },
    { version: '4.2.3', date: '2026-10-08', groups: [{ title: 'Correzioni', items: ['Prima.'] }] }]
  vi.spyOn(api, 'GET').mockResolvedValue(result(sections) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><ChangelogSection version="4.2.4b1" /></QueryClientProvider>)
  const current = (await screen.findByText('4.2.4b1')).closest('details')!
  expect(current).toHaveAttribute('open')
  expect(screen.getByText('4.2.3').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('<b>Testo semplice</b>')).toBeVisible()
  expect(current.querySelector('b')).toBeNull()
  await userEvent.click(screen.getByText('4.2.3'))
  expect(screen.getByText('Prima.')).toBeVisible()
})

it('Novità senza file mostra uno stato vuoto', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue(result([]) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><ChangelogSection version="4.2.4b1" /></QueryClientProvider>)
  expect(await screen.findByText('Nessuna nota disponibile.')).toBeVisible()
})

it('Novità conserva le caselle per versione e testo e permette di toglierle', async () => {
  localStorage.clear()
  const sections = [
    { version: '4.2.4b3', date: '', groups: [{ title: 'Correzioni', items: ['Voce uguale.', 'Voce diversa.'] }] },
    { version: '4.2.4b2', date: '', groups: [{ title: 'Correzioni', items: ['Voce uguale.'] }] },
  ]
  vi.spyOn(api, 'GET').mockResolvedValue(result(sections) as never)
  const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ChangelogSection version="4.2.4b3" /></QueryClientProvider>)
  const first = mount()
  const latest = within((await screen.findByText('4.2.4b3')).closest('details')!)
  await userEvent.click(latest.getByRole('checkbox', { name: 'Voce uguale.' }))
  expect(latest.getByText('Voce uguale.')).toHaveClass('line-through')
  first.unmount()
  mount()
  const current = within((await screen.findByText('4.2.4b3')).closest('details')!)
  expect(current.getByRole('checkbox', { name: 'Voce uguale.' })).toBeChecked()
  expect(current.getByRole('checkbox', { name: 'Voce diversa.' })).not.toBeChecked()
  await userEvent.click(screen.getByText('4.2.4b2'))
  expect(within(screen.getByText('4.2.4b2').closest('details')!).getByRole('checkbox', { name: 'Voce uguale.' })).not.toBeChecked()
  await userEvent.click(current.getByRole('checkbox', { name: 'Voce uguale.' }))
  expect(current.getByText('Voce uguale.')).not.toHaveClass('line-through')
  expect(localStorage.length).toBe(0)
})

it('Novità resta utilizzabile quando il browser non permette localStorage', async () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Bloccato') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Bloccato') })
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Bloccato') })
  try {
    vi.spyOn(api, 'GET').mockResolvedValue(result([{ version: '4.2.4b3', date: '', groups: [{ title: 'Correzioni', items: ['Voce.'] }] }]) as never)
    render(<QueryClientProvider client={new QueryClient()}><ChangelogSection version="4.2.4b3" /></QueryClientProvider>)
    const checkbox = await screen.findByRole('checkbox', { name: 'Voce.' })
    await userEvent.click(checkbox)
    expect(checkbox).toBeChecked()
    await userEvent.click(checkbox)
    expect(checkbox).not.toBeChecked()
  } finally { get.mockRestore(); set.mockRestore(); remove.mockRestore() }
})
