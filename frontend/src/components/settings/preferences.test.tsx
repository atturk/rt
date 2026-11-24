import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { PREFERENCES_KEY } from '@/lib/preferences'
import { getZoom, resetZoom, setZoom } from '@/lib/zoom'
import { getSavedStudyTextScale } from '@/lib/studyText'
import { AppearanceSection, OutlineSettingsSection, SpeedSection } from './preferences'
import { testSettings } from './testSettings'

// In jsdom il canvas non misura: tutti i font risultano installati.
vi.mock('@/lib/studyText', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/studyText')>(),
  studyFontAvailable: () => true,
}))

let client: QueryClient

beforeEach(() => {
  localStorage.clear()
  sessionStorage.setItem('rt-app', '1') // lo zoom di RT c'è solo nella finestra dell'app
  resetZoom()
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(PREFERENCES_KEY, {})
  vi.spyOn(api, 'GET').mockImplementation(() => Promise.resolve({ data: testSettings, response: new Response('{}', { status: 200 }) }) as never)
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
  resetZoom()
  localStorage.clear()
  sessionStorage.clear()
})

it('cambiare la Select aggiorna lo zoom', async () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const menuButton = screen.getByRole('button', { name: 'Zoom' })
  expect(menuButton).toBeInTheDocument()
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('100%')

  // Scegli 125%
  await userEvent.click(menuButton)
  const option125 = screen.getByRole('menuitemradio', { name: '125%' })
  await userEvent.click(option125)

  expect(getZoom()).toBe(1.25)
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('125%')

  // Reimposta a 100% dalla select
  await userEvent.click(menuButton)
  const option100 = screen.getByRole('menuitemradio', { name: '100%' })
  await userEvent.click(option100)

  expect(getZoom()).toBe(1)
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('100%')
})

it('evento rt-zoom-change aggiorna il controllo', async () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )

  act(() => {
    setZoom(1.5)
  })
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('150%')
})

it('Aspetto non ha più la sezione Studio né i colori dell’evidenziatore', () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )
  expect(screen.queryByText('Studio')).not.toBeInTheDocument()
  expect(screen.queryByText(/Colori dell.evidenziatore/)).not.toBeInTheDocument()
  expect(screen.queryByText('Frecce per cambiare unità')).not.toBeInTheDocument()
})

it('Testo dello Studio: Seravek salva study.text-font e 120% porta la scala a 1,2', async () => {
  const stored: Record<string, unknown> = {}
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve({ data: path === '/api/v1/preferences' ? stored : testSettings, response: new Response('{}') })) as never)
  const put = vi.spyOn(api, 'PUT').mockImplementation(((_path: string, { params, body }: { params: { path: { name: string } }; body: unknown }) => {
    stored[params.path.name] = body
    return Promise.resolve({ data: body, response: new Response('{}') })
  }) as never)
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Font' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: 'Seravek' }))
  expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'study.text-font' } }, body: 'seravek' })
  expect(screen.getByTestId('pref-study-font')).toHaveAttribute('data-value', 'seravek')

  await userEvent.click(screen.getByRole('button', { name: 'Dimensione' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: '120%' }))
  expect(getSavedStudyTextScale()).toBe(1.2)
  expect(screen.getByTestId('pref-study-scale')).toHaveTextContent('120%')

  const playerSwitch = screen.getByRole('switch', { name: "Il player segue l'unità" })
  expect(playerSwitch).toHaveAttribute('aria-checked', 'true')
  await userEvent.click(playerSwitch)
  expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'study.player-follows-unit' } }, body: false })
})

it('PDF esportati: logo e QR di RT sono attivi e si spegne salvando pdf.qr-sito', async () => {
  const put = vi.spyOn(api, 'PUT').mockImplementation(((_path: string, { body }: { body: unknown }) =>
    Promise.resolve({ data: body, response: new Response('{}') })) as never)
  render(<QueryClientProvider client={client}><AppearanceSection settings={testSettings} /></QueryClientProvider>)
  const qr = screen.getByRole('switch', { name: 'Logo e QR di RT («Rielaborato con RT») nella prima pagina' })
  expect(qr).toHaveAttribute('aria-checked', 'true')
  await userEvent.click(qr)
  expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'pdf.qr-sito' } }, body: false })
})

it('Fonti: i default per tipo di file, con Solo immagini l’uso si spegne e la guida si sceglie nell’import', async () => {
  const { SourceDefaultsSection } = await import('./preferences')
  const stored: Record<string, unknown> = {}
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve({ data: path === '/api/v1/preferences' ? stored : testSettings, response: new Response('{}') })) as never)
  vi.spyOn(api, 'PUT').mockImplementation(((_path: string, { params, body }: { params: { path: { name: string } }; body: unknown }) => {
    stored[params.path.name] = body
    return Promise.resolve({ data: body, response: new Response('{}') })
  }) as never)
  render(<QueryClientProvider client={client}><SourceDefaultsSection /></QueryClientProvider>)
  const { within } = await import('@testing-library/react')
  const slide = within(screen.getByTestId('source-default-slide'))
  expect(slide.getByRole('button', { name: 'Testo e immagini' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(screen.getByTestId('source-default-testo')).getByRole('button', { name: 'Testo' })).toHaveAttribute('aria-pressed', 'true')
  expect(slide.getByRole('button', { name: 'Guida: fonte principale' })).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(slide.getByRole('button', { name: 'Solo immagini' }))
  expect(slide.getByRole('button', { name: 'Solo immagini' })).toHaveAttribute('aria-pressed', 'true')
  expect(slide.getByRole('button', { name: 'Integra: può aggiungere unità' })).toHaveAttribute('aria-disabled', 'true')
})

it('Scaletta: in auto e manual nasconde i secondi, in timer li mostra e li salva', async () => {
  const put = vi.spyOn(api, 'PUT').mockImplementation(((_path: string, { body }: { body: Record<string, unknown> }) =>
    Promise.resolve({ data: { ...testSettings, preferences: { ...testSettings.preferences, ...body } }, response: new Response('{}') })) as never)
  render(<QueryClientProvider client={client}><OutlineSettingsSection settings={testSettings} /></QueryClientProvider>)

  expect(screen.getByTestId('pref-scaletta-mode')).toHaveTextContent('Procedi da sola')
  expect(screen.queryByLabelText('Approva da sola dopo (secondi)')).toBeNull()

  await userEvent.click(screen.getByRole('button', { name: 'Approvazione della scaletta' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: 'Attendi qualche secondo' }))
  expect(put).toHaveBeenCalledWith('/api/v1/settings/preferences', { body: expect.objectContaining({ modalita_scaletta: 'timer' }) })
  const secondsInput = screen.getByLabelText('Approva da sola dopo (secondi)')
  expect(secondsInput).toHaveValue(10)

  await userEvent.clear(secondsInput)
  await userEvent.type(secondsInput, '25')
  secondsInput.blur()
  await vi.waitFor(() => {
    expect(put).toHaveBeenLastCalledWith('/api/v1/settings/preferences', {
      body: expect.objectContaining({ modalita_scaletta: 'timer', secondi_approvazione: 25 }),
    })
  })

  await userEvent.click(screen.getByRole('button', { name: 'Approvazione della scaletta' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: 'Aspetta sempre me' }))
  expect(put).toHaveBeenLastCalledWith('/api/v1/settings/preferences', { body: expect.objectContaining({ modalita_scaletta: 'manual' }) })
  expect(screen.queryByLabelText('Approva da sola dopo (secondi)')).toBeNull()
})

it('Fonti: intestazione delle colonne una volta sola nella matrice', async () => {
  const { SourceDefaultsSection } = await import('./preferences')
  render(<QueryClientProvider client={client}><SourceDefaultsSection /></QueryClientProvider>)
  expect(screen.getAllByText('Cosa usare')).toHaveLength(1)
  expect(screen.getAllByText('Come usarla')).toHaveLength(1)
})

it('Velocità: Lavora in parallelo salva context_mode all quando spento', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: testSettings, response: new Response('{}') } as never)
  render(<QueryClientProvider client={client}><SpeedSection settings={testSettings} /></QueryClientProvider>)
  const sw = screen.getByRole('switch', { name: 'Lavora in parallelo' })
  expect(sw).toHaveAttribute('aria-checked', 'true')
  await userEvent.click(sw)
  expect(put).toHaveBeenCalledWith('/api/v1/settings/rewrite', { body: { context_mode: 'all' } })
})
