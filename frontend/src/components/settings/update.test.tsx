import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, type Schemas } from '@/api/client'
import { Layout } from '@/components/Layout'
import { testSettings } from '@/components/settings/testSettings'
import { InfoSettingsPage, SettingsLayout } from '@/routes/settings'
import { UpdateSection } from './update'
import { computeUpdateNotice } from './useAppUpdate'

const idle = { phase: 'idle', downloaded: 0, total: null, error: null, target: null }
const base: Schemas['AppUpdate'] = {
  supported: true,
  current: '4.2.5',
  latest: '4.3.0',
  available: true,
  channel: 'stable',
  prerelease: false,
  ready: false,
  asset_name: 'RT-4.3.0-windows-x64-setup.exe',
  asset_size: 300 * 1024 * 1024,
  notes_url: 'https://github.com/atturk/rt/releases/tag/v4.3.0',
  releases_url: 'https://github.com/atturk/rt/releases',
  error: null,
  progress: idle,
}

function result(data: unknown, status = 200) {
  return { data, response: new Response('{}', { status }) }
}

function renderUpdate(data: Schemas['AppUpdate'], initialPrefs: Record<string, unknown> = {}) {
  const prefs: Record<string, unknown> = { ...initialPrefs }
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/preferences') return Promise.resolve(result({ ...prefs }))
    return Promise.resolve(result(data))
  }) as never)
  const post = vi.spyOn(api, 'POST').mockImplementation(((path: string) => {
    if (path === '/api/v1/system/update/install') {
      return Promise.resolve(
        result(
          {
            ...data,
            ready: true,
            progress: {
              ...idle,
              phase: 'installing',
              target: data.latest ?? '4.3.0',
            },
          },
          202,
        ),
      )
    }
    return Promise.resolve(
      result(
        {
          ...data,
          progress: {
            ...idle,
            phase: 'downloading',
            downloaded: 150 * 1024 * 1024,
            total: 300 * 1024 * 1024,
            target: '4.3.0',
          },
        },
        202,
      ),
    )
  }) as never)
  const put = vi.spyOn(api, 'PUT').mockImplementation(((path: string, opts?: { params?: { path?: { name?: string } }; body?: unknown }) => {
    if (path === '/api/v1/preferences/{name}') {
      const name = opts?.params?.path?.name
      if (name) prefs[name] = opts?.body
      return Promise.resolve(result(undefined, 204))
    }
    return Promise.resolve(
      result(
        {
          ...data,
          channel: 'beta',
        },
        200,
      ),
    )
  }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <UpdateSection />
    </QueryClientProvider>,
  )
  return { post, put, prefs, container: view.container }
}

function renderAppShell(
  updateData: Schemas['AppUpdate'],
  {
    initialPath = '/',
    phone = false,
    initialPrefs = {},
    componentsData,
  }: { initialPath?: string; phone?: boolean; initialPrefs?: Record<string, unknown>; componentsData?: unknown } = {},
) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: phone && query.includes('max-width'),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  const prefs: Record<string, unknown> = { ...initialPrefs }
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/auth/me') return Promise.resolve(result({ actor: 'test' }))
    if (path === '/api/v1/system/update') return Promise.resolve(result(updateData))
    if (path === '/api/v1/components' && componentsData !== undefined) return Promise.resolve(result(componentsData))
    if (path === '/api/v1/preferences') return Promise.resolve(result({ ...prefs }))
    if (path === '/api/v1/jobs') return Promise.resolve(result([]))
    if (path === '/api/v1/workers') return Promise.resolve(result([{ id: 'w1' }]))
    if (path === '/api/v1/system/converters') return Promise.resolve(result({ pptx: { available: false, methods: [], platform: 'darwin' } }))
    if (path === '/api/v1/system/info') {
      return Promise.resolve(result({
        version: '4.2.5',
        prerelease: false,
        update_channel: 'stable',
        install_dir: '/app',
        data_dir: '/data',
        config_dir: '/config',
        python_version: '3.12.3',
        platform: 'Darwin',
        donazioni_url: '',
      }))
    }
    if (path === '/api/v1/system/cache') {
      return Promise.resolve(result({ audio: { entries: 0, bytes: 0 }, waveform: { entries: 0, bytes: 0 }, total: { entries: 0, bytes: 0 } }))
    }
    if (path === '/api/v1/system/compact-audio/preview') {
      return Promise.resolve(result({ file_convertibili: 0, bytes_convertibili: 0, file_orfani: 0, bytes_orfani: 0, spazio_stimato_liberato: 0 }))
    }
    if (path === '/api/v1/system/changelog') return Promise.resolve(result([]))
    if (path === '/api/v1/settings') return Promise.resolve(result(testSettings))
    return Promise.resolve(result({}))
  }) as never)
  const put = vi.spyOn(api, 'PUT').mockImplementation(((path: string, opts?: { params?: { path?: { name?: string } }; body?: unknown }) => {
    if (path === '/api/v1/preferences/{name}') {
      const name = opts?.params?.path?.name
      if (name) prefs[name] = opts?.body
      return Promise.resolve(result(undefined, 204))
    }
    return Promise.resolve(result({}, 200))
  }) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <Layout />,
        children: [
          { index: true, element: <p>Pagina lezioni</p> },
          {
            path: 'impostazioni',
            element: <SettingsLayout />,
            children: [
              { path: 'aspetto', element: <p>Aspetto</p> },
              { path: 'lavorazione', element: <p>Lavorazione</p> },
              { path: 'info-aggiornamenti', element: <InfoSettingsPage /> },
            ],
          },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { put, prefs, router }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
  sessionStorage.clear()
  delete (window as unknown as { pywebview?: unknown }).pywebview
})

describe('Aggiornamenti', () => {
  it("nell'app installata scarica la versione disponibile con barra determinata, MB e testo di avviso", async () => {
    const { post, container } = renderUpdate(base)
    expect(await screen.findByText('4.3.0')).toBeVisible()
    const downloadBtn = screen.getByRole('button', { name: /Scarica/ })
    await userEvent.click(downloadBtn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update')

    expect(await screen.findByRole('status')).toHaveTextContent('Scarico RT 4.3.0…')
    const progress = container.querySelector('progress')
    expect(progress).not.toBeNull()
    expect(progress).toHaveAttribute('value', '50')
    expect(progress).toHaveAttribute('max', '100')
    expect(progress).toHaveClass('max-w-sm', 'accent-primary')
    expect(screen.getByText('50% · 150.0 MB / 300.0 MB')).toBeVisible()
    expect(
      screen.getByText(
        "Download avviato: puoi continuare a usare RT. Quando finisce, o se qualcosa va storto, lo vedi qui e sull'icona delle Impostazioni.",
      ),
    ).toBeVisible()
  })

  it('quando il file è pronto mostra Installa e riavvia e al clic mostra solo "Riavvio in corso…" senza progress', async () => {
    const { post, container } = renderUpdate({ ...base, ready: true, progress: { ...idle, phase: 'ready' } })
    const btn = await screen.findByRole('button', { name: /Installa e riavvia/ })
    expect(btn).toBeVisible()
    await userEvent.click(btn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update/install')
    expect(await screen.findByRole('status')).toHaveTextContent('Riavvio in corso…')
    expect(container.querySelector('progress')).toBeNull()
    expect(screen.getByRole('button', { name: /Installa e riavvia/ })).toBeDisabled()
  })

  it('in fase installing non mostra alcuna barra <progress> e disabilita il pulsante', async () => {
    const { container } = renderUpdate({
      ...base,
      ready: true,
      progress: { ...idle, phase: 'installing', target: '4.3.0' },
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Riavvio in corso…')
    expect(container.querySelector('progress')).toBeNull()
    expect(screen.getByRole('button', { name: /Installa e riavvia/ })).toBeDisabled()
  })

  it('senza app installata non offre il pulsante', async () => {
    renderUpdate({ ...base, supported: false, available: false })
    expect(await screen.findByText(/Ultima versione/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /Scarica/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pagina delle release' })).toHaveAttribute('href', base.releases_url)
  })

  it('aggiornato: nessun pulsante di download o installazione', async () => {
    renderUpdate({ ...base, latest: '4.2.5', available: false })
    expect(await screen.findByText('RT è aggiornato.')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Scarica/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Installa e riavvia/ })).not.toBeInTheDocument()
  })

  it('cambia canale con lo switch Beta', async () => {
    const { put } = renderUpdate(base)
    const betaSwitch = await screen.findByRole('switch', { name: /Beta/i })
    expect(betaSwitch).not.toBeChecked()
    await userEvent.click(betaSwitch)
    expect(put).toHaveBeenCalledWith('/api/v1/system/update/channel', { body: { channel: 'beta' } })
  })
})

describe('Avviso e pallino aggiornamenti', () => {
  it('computeUpdateNotice distingue available, ready, error e ignora fasi busy o già viste', () => {
    expect(computeUpdateNotice(base, null)).toEqual({ notice: 'available', seenKey: '4.3.0:available' })
    expect(computeUpdateNotice(base, '4.3.0:available')).toEqual({ notice: null, seenKey: '4.3.0:available' })

    const readyData = { ...base, ready: true, progress: { ...idle, phase: 'ready' } }
    expect(computeUpdateNotice(readyData, '4.3.0:available')).toEqual({ notice: 'ready', seenKey: '4.3.0:ready' })
    expect(computeUpdateNotice(readyData, '4.3.0:ready')).toEqual({ notice: null, seenKey: '4.3.0:ready' })

    const errData = { ...base, progress: { ...idle, phase: 'error', error: 'Rete assente', target: '4.3.0' } }
    expect(computeUpdateNotice(errData, '4.3.0:ready')).toEqual({ notice: 'error', seenKey: '4.3.0:error' })
    expect(computeUpdateNotice(errData, '4.3.0:error')).toEqual({ notice: null, seenKey: '4.3.0:error' })

    const busyData = { ...base, progress: { ...idle, phase: 'downloading', target: '4.3.0' } }
    expect(computeUpdateNotice(busyData, null)).toEqual({ notice: null, seenKey: null })
  })

  it('mostra il pallino ready su Impostazioni e nella voce Info e aggiornamenti, e non chiama mai apri_aggiornamento dal Layout', async () => {
    const apriMock = vi.fn()
    window.pywebview = { api: { salva_copia_backup: vi.fn(), apri_aggiornamento: apriMock } }
    sessionStorage.setItem('rt-app', '1')

    renderAppShell(
      { ...base, ready: true, progress: { ...idle, phase: 'ready', target: '4.3.0' } },
      { initialPath: '/impostazioni/aspetto' },
    )

    const settingsNavLink = await screen.findByRole('link', { name: 'Impostazioni' })
    expect(await within(settingsNavLink).findByLabelText('Aggiornamento pronto')).toBeInTheDocument()

    const sectionsNav = screen.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
    const infoLink = within(sectionsNav).getByRole('link', { name: /Info e aggiornamenti/ })
    expect(await within(infoLink).findByLabelText('Aggiornamento pronto')).toBeInTheDocument()

    await new Promise((r) => setTimeout(r, 50))
    expect(apriMock).not.toHaveBeenCalled()
  })

  it('mostra il pallino error anche su telefono e lo spegne aprendo Info e aggiornamenti ("visto")', async () => {
    const errData: Schemas['AppUpdate'] = {
      ...base,
      progress: { ...idle, phase: 'error', error: 'Impossibile montare il .dmg', target: '4.3.0' },
    }
    const { put } = renderAppShell(errData, { initialPath: '/impostazioni', phone: true })

    const settingsNavLink = await screen.findByRole('link', { name: 'Impostazioni' })
    expect(await within(settingsNavLink).findByLabelText('Aggiornamento non riuscito')).toBeInTheDocument()

    const sectionsNav = screen.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
    const infoLink = within(sectionsNav).getByRole('link', { name: /Info e aggiornamenti/ })
    expect(await within(infoLink).findByLabelText('Aggiornamento non riuscito')).toBeInTheDocument()

    // Aprendo Info e aggiornamenti scrive update.seen e spegne il pallino
    await userEvent.click(infoLink)
    expect(await screen.findByText('Impossibile montare il .dmg')).toBeVisible()
    await waitFor(() => {
      expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', {
        params: { path: { name: 'update.seen' } },
        body: '4.3.0:error',
      })
    })
    await waitFor(() => {
      expect(screen.queryAllByTestId('update-notice-dot')).toHaveLength(0)
    })
  })

  it('mostra il pallino su Impostazioni e Lavorazione delle lezioni quando manca il componente richiesto e clic porta a #componenti', async () => {
    const noUpdate = { ...base, available: false, ready: false, progress: idle }
    const missingMac = {
      id: 'macparakeet',
      name: 'Motore di trascrizione',
      description: "necessario per trascrivere l'audio",
      detail: 'macparakeet + modello parakeet-v3',
      required: true,
      state: 'not_downloaded',
      downloaded_bytes: 0,
      total_bytes: null,
      approx_bytes: 500 * 1024 * 1024,
      percent: null,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
    }
    const { router } = renderAppShell(noUpdate, { initialPath: '/impostazioni/aspetto', componentsData: [missingMac] })

    const settingsNavLink = await screen.findByRole('link', { name: 'Impostazioni' })
    expect(await within(settingsNavLink).findByLabelText('Motore di trascrizione da scaricare')).toBeInTheDocument()

    const sectionsNav = screen.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
    const workLink = within(sectionsNav).getByRole('link', { name: /Lavorazione delle lezioni/ })
    expect(await within(workLink).findByLabelText('Motore di trascrizione da scaricare')).toBeInTheDocument()
    expect(workLink).toHaveAttribute('href', '/impostazioni/lavorazione')

    await userEvent.click(workLink)
    expect(router.state.location.pathname).toBe('/impostazioni/lavorazione')
  })

  it('nasconde il pallino del componente quando è in download o pronto', async () => {
    const noUpdate = { ...base, available: false, ready: false, progress: idle }
    const downloadingMac = {
      id: 'macparakeet',
      name: 'Motore di trascrizione',
      description: "necessario per trascrivere l'audio",
      detail: 'macparakeet + modello parakeet-v3',
      required: true,
      state: 'downloading',
      downloaded_bytes: 100 * 1024 * 1024,
      total_bytes: 500 * 1024 * 1024,
      approx_bytes: 500 * 1024 * 1024,
      percent: 20,
      eta_seconds: 60,
      eta_label: 'circa 1 min',
      error: null,
      available: true,
      unavailable_reason: null,
    }
    renderAppShell(noUpdate, { initialPath: '/impostazioni/aspetto', componentsData: [downloadingMac] })
    await screen.findByRole('link', { name: 'Impostazioni' })
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryAllByTestId('component-notice-dot')).toHaveLength(0)
  })

  it('non mostra il pallino quando il browser di sistema è rilevato (required false)', async () => {
    const noUpdate = { ...base, available: false, ready: false, progress: idle }
    const readyMac = {
      id: 'macparakeet',
      name: 'Motore di trascrizione',
      description: 'usato da RT per trascrivere l\'audio',
      detail: 'macparakeet + modello parakeet-v3',
      required: true,
      state: 'ready',
      downloaded_bytes: 500 * 1024 * 1024,
      total_bytes: 500 * 1024 * 1024,
      approx_bytes: 500 * 1024 * 1024,
      percent: 100,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
    }
    const systemBrowser = {
      id: 'browser',
      name: 'Browser per PDF e catture',
      description: 'Rilevato Microsoft Edge: RT usa quello',
      detail: 'Chrome Headless Shell (versione minima)',
      required: false,
      state: 'not_downloaded',
      downloaded_bytes: 0,
      total_bytes: null,
      approx_bytes: 110 * 1024 * 1024,
      percent: null,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
      system_browser: 'Microsoft Edge',
      in_use: 'system',
    }
    renderAppShell(noUpdate, { initialPath: '/impostazioni/aspetto', componentsData: [readyMac, systemBrowser] })
    await screen.findByRole('link', { name: 'Impostazioni' })
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryAllByTestId('component-notice-dot')).toHaveLength(0)
  })

  it('mostra il pallino per il solo browser mancante (nessun browser di sistema)', async () => {
    const noUpdate = { ...base, available: false, ready: false, progress: idle }
    const missingBrowser = {
      id: 'browser',
      name: 'Browser per PDF e catture',
      description: 'Serve per esportare in PDF e per le visualizzazioni: scaricalo',
      detail: 'Chrome Headless Shell (versione minima)',
      required: true,
      state: 'not_downloaded',
      downloaded_bytes: 0,
      total_bytes: null,
      approx_bytes: 110 * 1024 * 1024,
      percent: null,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
      system_browser: null,
      in_use: null,
    }
    renderAppShell(noUpdate, { initialPath: '/impostazioni/aspetto', componentsData: [missingBrowser] })

    const settingsNavLink = await screen.findByRole('link', { name: 'Impostazioni' })
    expect(await within(settingsNavLink).findByLabelText('Browser per PDF e catture da scaricare')).toBeInTheDocument()

    const sectionsNav = screen.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
    const workLink = within(sectionsNav).getByRole('link', { name: /Lavorazione delle lezioni/ })
    expect(await within(workLink).findByLabelText('Browser per PDF e catture da scaricare')).toBeInTheDocument()
  })

  it('mostra etichetta al plurale quando mancano due componenti richiesti', async () => {
    const noUpdate = { ...base, available: false, ready: false, progress: idle }
    const missingMac = {
      id: 'macparakeet',
      name: 'Motore di trascrizione',
      description: "usato da RT per trascrivere l'audio",
      detail: 'macparakeet + modello parakeet-v3',
      required: true,
      state: 'not_downloaded',
      downloaded_bytes: 0,
      total_bytes: null,
      approx_bytes: 500 * 1024 * 1024,
      percent: null,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
    }
    const missingBrowser = {
      id: 'browser',
      name: 'Browser per PDF e catture',
      description: 'Serve per esportare in PDF e per le visualizzazioni: scaricalo',
      detail: 'Chrome Headless Shell (versione minima)',
      required: true,
      state: 'not_downloaded',
      downloaded_bytes: 0,
      total_bytes: null,
      approx_bytes: 110 * 1024 * 1024,
      percent: null,
      eta_seconds: null,
      eta_label: null,
      error: null,
      available: true,
      unavailable_reason: null,
      system_browser: null,
      in_use: null,
    }
    renderAppShell(noUpdate, { initialPath: '/impostazioni/aspetto', componentsData: [missingMac, missingBrowser] })

    const settingsNavLink = await screen.findByRole('link', { name: 'Impostazioni' })
    expect(await within(settingsNavLink).findByLabelText('Componenti da scaricare')).toBeInTheDocument()

    const sectionsNav = screen.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
    const workLink = within(sectionsNav).getByRole('link', { name: /Lavorazione delle lezioni/ })
    expect(await within(workLink).findByLabelText('Componenti da scaricare')).toBeInTheDocument()
  })
})
