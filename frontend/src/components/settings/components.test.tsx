import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { ComponentStatus } from '@/api/components'
import type { ConvertersInfo } from '@/api/converters'
import { ComponentsSection } from './components'

const ok = (data: unknown) => ({ data, error: undefined, response: new Response(JSON.stringify(data), { status: 200 }) }) as never

const baseTranscription: ComponentStatus = {
  id: 'transcription',
  name: 'Modello di trascrizione',
  description: "necessario per trascrivere l'audio",
  detail: 'Parakeet ONNX + VAD',
  required: true,
  state: 'not_downloaded',
  downloaded_bytes: 0,
  total_bytes: null,
  approx_bytes: 670 * 1024 * 1024,
  percent: null,
  eta_seconds: null,
  eta_label: null,
  error: null,
  available: true,
  unavailable_reason: null,
}

const baseMacparakeet: ComponentStatus = {
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

const baseBrowser: ComponentStatus = {
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
  system_app: null,
  in_use: null,
}

const baseLibreOffice: ComponentStatus = {
  id: 'libreoffice',
  name: 'Convertitore delle presentazioni',
  description: 'Serve per trasformare le presentazioni (.pptx) in slide: scaricalo',
  detail: 'LibreOffice 26.8.3 (MPL-2.0)',
  required: true,
  state: 'not_downloaded',
  downloaded_bytes: 0,
  total_bytes: null,
  approx_bytes: 299927705,
  percent: null,
  eta_seconds: null,
  eta_label: null,
  error: null,
  available: true,
  unavailable_reason: null,
  system_browser: null,
  system_app: null,
  in_use: null,
}

function renderComponents(
  components: ComponentStatus[],
  pptx: ConvertersInfo['pptx'] = { available: true, methods: ['LibreOffice'], quicklook_available: false, platform: 'darwin' },
  transcriptionSettings?: Record<string, unknown>,
) {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/components') return Promise.resolve(ok(components))
    if (path === '/api/v1/system/converters') return Promise.resolve(ok({ pptx }))
    if (path === '/api/v1/settings' && transcriptionSettings) {
      return Promise.resolve(ok({ transcription: transcriptionSettings }))
    }
    return Promise.resolve(ok({}))
  }) as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ComponentsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ComponentsSection', () => {
  it('mostra le righe, i diversi stati e le azioni Scarica / Pausa / Riprendi / Riprova / Elimina', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseTranscription, state: 'downloading' }))
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(baseBrowser))

    renderComponents([
      {
        ...baseTranscription,
        state: 'downloading',
        downloaded_bytes: 281 * 1024 * 1024,
        total_bytes: 670 * 1024 * 1024,
        percent: 42,
        eta_seconds: 360,
        eta_label: 'circa 6 min',
      },
      {
        ...baseBrowser,
        state: 'ready',
        description: 'RT usa il browser scaricato per esportare in PDF e per le visualizzazioni',
        in_use: 'component',
        downloaded_bytes: 165 * 1024 * 1024,
        total_bytes: 165 * 1024 * 1024,
        percent: 100,
      },
    ])

    const transRow = await screen.findByTestId('component-row-transcription')
    expect(transRow).toHaveTextContent('Modello di trascrizione')
    expect(transRow).toHaveTextContent("necessario per trascrivere l'audio")
    expect(transRow).toHaveTextContent('42%')
    expect(transRow).toHaveTextContent('circa 6 min')
    expect(within(transRow).getByTestId('component-badge-transcription')).toHaveTextContent('In download')

    const user = userEvent.setup()
    await user.click(within(transRow).getByRole('button', { name: 'Pausa' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/cancel', { params: { path: { component_id: 'transcription' } } })

    const browserRow = screen.getByTestId('component-row-browser')
    expect(browserRow).toHaveTextContent('Browser per PDF e catture')
    expect(browserRow).toHaveTextContent('RT usa il browser scaricato per esportare in PDF e per le visualizzazioni')
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Pronto')
    expect(within(browserRow).queryByTestId('component-row-dot-browser')).toBeNull()
    await user.click(within(browserRow).getByRole('button', { name: 'Elimina' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Elimina' }))
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith('/api/v1/components/{component_id}', { params: { path: { component_id: 'browser' } } }),
    )
  })

  it('mostra Riprendi su pausa e Riprova su errore', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseTranscription, state: 'downloading' }))
    renderComponents([
      { ...baseTranscription, state: 'paused', downloaded_bytes: 100 * 1024 * 1024, total_bytes: 670 * 1024 * 1024, percent: 15 },
      { ...baseBrowser, state: 'error', error: 'Rete assente' },
    ])

    const user = userEvent.setup()
    const transRow = await screen.findByTestId('component-row-transcription')
    expect(within(transRow).getByTestId('component-badge-transcription')).toHaveTextContent('In pausa')
    await user.click(within(transRow).getByRole('button', { name: 'Riprendi' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'transcription' } } })

    const browserRow = screen.getByTestId('component-row-browser')
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Errore')
    expect(browserRow).toHaveTextContent('Rete assente')
    await user.click(within(browserRow).getByRole('button', { name: 'Riprova' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'browser' } } })
  })

  it.each([
    {
      pptx: { available: true, methods: ['LibreOffice'], quicklook_available: false, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: LibreOffice',
      badge: 'Pronto',
    },
    {
      pptx: { available: true, methods: ['PowerPoint'], quicklook_available: false, platform: 'win32' },
      expected: 'Presentazioni .pptx convertite con: PowerPoint',
      badge: 'Pronto',
    },
    {
      pptx: { available: true, methods: ['Keynote'], quicklook_available: false, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: Keynote',
      badge: 'Pronto',
    },
    {
      pptx: { available: false, methods: [], quicklook_available: true, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: Quick Look (qualità ridotta)',
      badge: 'Qualità ridotta',
    },
    {
      pptx: { available: false, methods: [], quicklook_available: false, platform: 'win32' },
      expected: 'Presentazioni .pptx convertite con: nessuno (solo testo)',
      badge: 'Solo testo',
    },
  ])('riga Presentazioni: $expected', async ({ pptx, expected, badge }) => {
    renderComponents([baseTranscription], pptx)
    const row = await screen.findByTestId('presentations-row')
    await waitFor(() => expect(row).toHaveTextContent(expected))
    expect(row).toHaveTextContent(badge)
  })

  it('sul Mac con macparakeet mostra Motore di trascrizione e nasconde ONNX; con ONNX mostra entrambi; su Windows solo ONNX', async () => {
    // Mac con macparakeet
    renderComponents([baseMacparakeet, baseTranscription, baseBrowser], undefined, {
      engine: 'macparakeet',
      effective_engine: 'macparakeet',
      macparakeet_available: true,
    })
    expect(await screen.findByTestId('component-row-macparakeet')).toHaveTextContent('Motore di trascrizione')
    expect(screen.getByTestId('component-row-browser')).toBeVisible()
    expect(screen.queryByTestId('component-row-transcription')).toBeNull()

    // Mac con Parakeet ONNX selezionato
    cleanup(); vi.restoreAllMocks()
    renderComponents([baseMacparakeet, baseTranscription, baseBrowser], undefined, {
      engine: 'parakeet',
      effective_engine: 'parakeet',
      macparakeet_available: true,
    })
    expect(await screen.findByTestId('component-row-macparakeet')).toBeVisible()
    expect(screen.getByTestId('component-row-transcription')).toBeVisible()

    // Windows: macparakeet non disponibile -> solo ONNX + browser
    cleanup(); vi.restoreAllMocks()
    renderComponents(
      [{ ...baseMacparakeet, available: false, required: false }, baseTranscription, baseBrowser],
      undefined,
      { engine: 'parakeet', effective_engine: 'parakeet', macparakeet_available: false },
    )
    expect(await screen.findByTestId('component-row-transcription')).toBeVisible()
    expect(screen.queryByTestId('component-row-macparakeet')).toBeNull()
  })

  it('browser di sistema rilevato: nessun pallino, badge Non necessario e Scarica presente', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseBrowser, state: 'downloading' }))
    renderComponents([
      { ...baseTranscription, state: 'ready' },
      {
        ...baseBrowser,
        required: false,
        system_browser: 'Microsoft Edge',
        in_use: 'system',
        description:
          'Rilevato Microsoft Edge: RT usa quello, scaricare questo componente non è necessario. Se lo scarichi, RT usa questo',
      },
    ])

    const browserRow = await screen.findByTestId('component-row-browser')
    expect(within(browserRow).queryByTestId('component-row-dot-browser')).toBeNull()
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Non necessario')
    expect(browserRow).toHaveTextContent('Rilevato Microsoft Edge: RT usa quello, scaricare questo componente non è necessario.')

    const user = userEvent.setup()
    await user.click(within(browserRow).getByRole('button', { name: 'Scarica' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'browser' } } })
  })

  it('nessun browser e componente trascrizione richiesto: mostra pallino sulla riga solo quando mancante', async () => {
    renderComponents([
      baseTranscription,
      baseBrowser,
    ])

    const transRow = await screen.findByTestId('component-row-transcription')
    const browserRow = screen.getByTestId('component-row-browser')
    expect(within(transRow).getByTestId('component-row-dot-transcription')).toBeInTheDocument()
    expect(within(browserRow).getByTestId('component-row-dot-browser')).toBeInTheDocument()
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Non scaricato')
    expect(browserRow).toHaveTextContent('Serve per esportare in PDF e per le visualizzazioni: scaricalo')
  })

  it('libreoffice con app di sistema rilevata: nessun pallino, badge Non necessario e Scarica presente', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseLibreOffice, state: 'downloading' }))
    renderComponents([
      { ...baseTranscription, state: 'ready' },
      {
        ...baseLibreOffice,
        required: false,
        system_app: 'Keynote',
        in_use: 'system',
        description: 'Rilevato Keynote: RT usa quello, scaricare questo componente non è necessario',
      },
    ])

    const loRow = await screen.findByTestId('component-row-libreoffice')
    expect(within(loRow).queryByTestId('component-row-dot-libreoffice')).toBeNull()
    expect(within(loRow).getByTestId('component-badge-libreoffice')).toHaveTextContent('Non necessario')
    expect(loRow).toHaveTextContent('Rilevato Keynote: RT usa quello, scaricare questo componente non è necessario')
    expect(loRow).toHaveTextContent('LibreOffice 26.8.3 (MPL-2.0)')

    const user = userEvent.setup()
    await user.click(within(loRow).getByRole('button', { name: 'Scarica' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'libreoffice' } } })
  })

  it('libreoffice mancante o Keynote bloccato: mostra pallino sulla riga e messaggio Preparo… al 99%', async () => {
    renderComponents([
      { ...baseTranscription, state: 'ready' },
      {
        ...baseLibreOffice,
        description:
          'Keynote non risponde: consenti a RT di controllarlo in Impostazioni di Sistema › Privacy e sicurezza › Automazione, oppure scarica il convertitore',
      },
    ])

    const loRow = await screen.findByTestId('component-row-libreoffice')
    expect(within(loRow).getByTestId('component-row-dot-libreoffice')).toBeInTheDocument()
    expect(within(loRow).getByTestId('component-badge-libreoffice')).toHaveTextContent('Non scaricato')
    expect(loRow).toHaveTextContent('Keynote non risponde: consenti a RT di controllarlo')

    cleanup()
    renderComponents([
      { ...baseTranscription, state: 'ready' },
      {
        ...baseLibreOffice,
        state: 'downloading',
        downloaded_bytes: 299927705,
        total_bytes: 299927705,
        percent: 99,
        eta_label: 'Preparo…',
      },
    ])

    const downloadingRow = await screen.findByTestId('component-row-libreoffice')
    expect(within(downloadingRow).queryByTestId('component-row-dot-libreoffice')).toBeNull()
    expect(downloadingRow).toHaveTextContent('99%')
    expect(downloadingRow).toHaveTextContent('Preparo…')
  })
})
