import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { renderHook } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, afterEach } from 'vitest'

import { api, type Schemas } from '@/api/client'
import { UpdatePopup } from './UpdatePopup'
import { useUpdatePopup } from './useAppUpdate'

const idle = { phase: 'idle', downloaded: 0, total: null, error: null, target: null }

const basePopupData: Schemas['AppUpdate'] = {
  supported: true,
  current: '4.2.5',
  latest: '4.3.0',
  available: true,
  channel: 'stable',
  prerelease: false,
  ready: false,
  asset_name: 'RT-4.3.0-macos-arm64.dmg',
  asset_size: 250 * 1024 * 1024,
  notes_url: 'https://github.com/atturk/rt/releases/tag/v4.3.0',
  releases_url: 'https://github.com/atturk/rt/releases',
  error: null,
  progress: idle,
}

function result(data: unknown, status = 200) {
  return { data, response: new Response('{}', { status }) }
}

function renderPopup(data: Schemas['AppUpdate']) {
  vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result(data))) as never)
  const post = vi.spyOn(api, 'POST').mockImplementation((() => Promise.resolve(result(data, 202))) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <UpdatePopup />
    </QueryClientProvider>,
  )
  return { post }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  sessionStorage.clear()
  delete (window as unknown as { pywebview?: unknown }).pywebview
})

describe('UpdatePopup', () => {
  it('controlla gli aggiornamenti una volta sola all\'apertura', async () => {
    renderPopup(basePopupData)
    expect(await screen.findByText('RT 4.3.0')).toBeVisible()
    await new Promise(resolve => setTimeout(resolve, 200))
    const refreshes = vi.mocked(api.GET).mock.calls.filter(call => JSON.stringify(call).includes('refresh'))
    expect(refreshes).toHaveLength(1)
  })

  it('stato disponibile: mostra versione, link novità e pulsante Scarica', async () => {
    const { post } = renderPopup(basePopupData)
    expect(await screen.findByText('RT 4.3.0')).toBeVisible()
    expect(screen.getByRole('link', { name: 'novità' })).toHaveAttribute('href', basePopupData.notes_url)
    const btn = screen.getByRole('button', { name: /Scarica/ })
    await userEvent.click(btn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update')
  })

  it('stato in download: mostra barra di avanzamento e percentuale', async () => {
    renderPopup({
      ...basePopupData,
      progress: {
        ...idle,
        phase: 'downloading',
        downloaded: 125 * 1024 * 1024,
        total: 250 * 1024 * 1024,
        target: '4.3.0',
      },
    })
    expect(await screen.findByRole('progressbar')).toHaveAttribute('value', '50')
    expect(screen.getByText('50%')).toBeVisible()
    expect(screen.getByText(/Scarico RT 4.3.0/)).toBeVisible()
  })

  it('stato pronto: mostra pulsante Installa e riavvia', async () => {
    const { post } = renderPopup({
      ...basePopupData,
      ready: true,
      progress: { ...idle, phase: 'ready' },
    })
    const installBtn = await screen.findByRole('button', { name: 'Installa e riavvia' })
    expect(installBtn).toBeVisible()
    await userEvent.click(installBtn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update/install')
  })

  it('stato errore: mostra Alert e pulsante Riprova', async () => {
    const { post } = renderPopup({
      ...basePopupData,
      progress: { ...idle, phase: 'error', error: 'Download interrotto: timeout' },
    })
    expect(await screen.findByText('Download interrotto: timeout')).toBeVisible()
    const retryBtn = screen.getByRole('button', { name: 'Riprova' })
    await userEvent.click(retryBtn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update')
  })

  it('mostra badge beta se la versione è una prerelease', async () => {
    renderPopup({
      ...basePopupData,
      latest: '4.3.1b1',
      prerelease: true,
    })
    expect(await screen.findByText('RT 4.3.1b1')).toBeVisible()
    expect(screen.getByText('beta')).toBeVisible()
  })
})

describe('useUpdatePopup', () => {
  it('chiama apri_aggiornamento con ready', async () => {
    const apriMock = vi.fn()
    window.pywebview = { api: { salva_copia_backup: vi.fn(), apri_aggiornamento: apriMock } }
    sessionStorage.setItem('rt-app', '1')

    vi.spyOn(api, 'GET').mockImplementation((() =>
      Promise.resolve(result({ ...basePopupData, ready: true, progress: { ...idle, phase: 'ready' } }))) as never)

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderHook(() => useUpdatePopup(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })

    await vi.waitFor(() => {
      expect(apriMock).toHaveBeenCalledTimes(1)
    })
  })

  it('chiama apri_aggiornamento una sola volta per versione con available', async () => {
    const apriMock = vi.fn()
    window.pywebview = { api: { salva_copia_backup: vi.fn(), apri_aggiornamento: apriMock } }
    sessionStorage.setItem('rt-app', '1')

    vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result(basePopupData))) as never)

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = renderHook(() => useUpdatePopup(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })

    await vi.waitFor(() => {
      expect(apriMock).toHaveBeenCalledTimes(1)
    })

    // Rerender non richiama apri_aggiornamento per la stessa versione
    rerender()
    expect(apriMock).toHaveBeenCalledTimes(1)
  })
})

it('se l’installazione non parte mostra il motivo dato da RT', async () => {
  renderPopup({ ...basePopupData, ready: true, progress: { ...idle, phase: 'ready' } })
  vi.spyOn(api, 'POST').mockImplementation((() => Promise.resolve({
    error: { error: { code: 'not_ready', message: 'Hash dell’installer non corrispondente.' } },
    response: new Response('{}', { status: 409 }),
  })) as never)
  await userEvent.click(await screen.findByRole('button', { name: 'Installa e riavvia' }))
  expect(await screen.findByText('Installazione non riuscita: Hash dell’installer non corrispondente.')).toBeInTheDocument()
})
