import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { NewLessonContext } from '@/components/shell/newLesson'
import { testSettings } from './testSettings'
import { SetupWizard } from './wizard'

const ok = (data: unknown, headers?: Record<string, string>) =>
  ({ data, error: undefined, response: new Response(JSON.stringify(data), { status: 200, headers }) }) as never

const emptySettings: Settings = {
  ...testSettings,
  setup_required: true,
  connections: [],
  credentials: [],
  phases: testSettings.phases.map((p) => ({ ...p, connection: null, model: null })),
}

function renderWizard(entry: string, settings: Settings = emptySettings, onOpenNewLesson = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <NewLessonContext value={onOpenNewLesson}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/impostazioni/configurazione" element={<SetupWizard settings={settings} />} />
            <Route path="/impostazioni/telegram/collega" element={<p>Schermata Telegram</p>} />
            <Route path="/impostazioni/modelli" element={<p>Modelli</p>} />
            <Route path="/lezioni/:id" element={<p>Lezione di esempio aperta</p>} />
            <Route path="/" element={<p>Elenco lezioni</p>} />
          </Routes>
        </MemoryRouter>
      </NewLessonContext>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SetupWizard: 3 passi e Connessione', () => {
  it('mostra 3 passi, reindirizza ?passo=4 a 3 e mostra Configura dopo solo sui primi due passi', () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({ available: false }))
    renderWizard('/impostazioni/configurazione?passo=1')
    const nav = screen.getByRole('list', { name: 'Passi' })
    expect(within(nav).getAllByRole('button').map((b) => b.textContent)).toEqual(['1Connessione', '2Modello', '3Pronto'])
    expect(screen.getByRole('button', { name: 'Configura dopo' })).toBeVisible()
    cleanup()

    renderWizard('/impostazioni/configurazione?passo=4')
    expect(screen.getByRole('heading', { name: 'RT è pronto' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Configura dopo' })).toBeNull()
  })

  it('mostra il popup ? per OpenRouter, Google AI Studio e DeepSeek, ma non per Altro', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({ available: false }))
    renderWizard('/impostazioni/configurazione?passo=1')
    const user = userEvent.setup()

    // OpenRouter (default)
    await user.click(screen.getByRole('button', { name: 'Come ottenere una chiave API' }))
    const dialog1 = screen.getByRole('dialog')
    expect(dialog1).toHaveTextContent('Come ottenere una chiave OpenRouter')
    expect(within(dialog1).getByRole('link', { name: /openrouter\.ai\/keys/ })).toHaveAttribute('href', 'https://openrouter.ai/keys')
    await user.click(within(dialog1).getByRole('button', { name: 'Chiudi' }))
    expect(screen.queryByRole('dialog')).toBeNull()

    // Google AI Studio
    await user.click(screen.getByRole('radio', { name: 'Google AI Studio' }))
    await user.click(screen.getByRole('button', { name: 'Come ottenere una chiave API' }))
    const dialog2 = screen.getByRole('dialog')
    expect(dialog2).toHaveTextContent('Come ottenere una chiave Google AI Studio')
    fireEvent(dialog2, new Event('cancel', { cancelable: true }))
    expect(screen.queryByRole('dialog')).toBeNull()

    // DeepSeek
    await user.click(screen.getByRole('radio', { name: 'DeepSeek' }))
    await user.click(screen.getByRole('button', { name: 'Come ottenere una chiave API' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Come ottenere una chiave DeepSeek')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Chiudi' }))

    // Altro -> niente ? e mostra Nome connessione / Base URL
    await user.click(screen.getByRole('radio', { name: /Altro/ }))
    expect(screen.queryByRole('button', { name: 'Come ottenere una chiave API' })).toBeNull()
    expect(screen.getByLabelText('Nome connessione')).toBeVisible()
    expect(screen.getByLabelText('Base URL')).toBeVisible()
  })

  it('verifica la chiave incollata senza salvare fino a Continua, mostra/nasconde con occhio e chiede conferma sul cestino pieno', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({ available: false }))
    const post = vi.spyOn(api, 'POST').mockImplementation(((path: string) => {
      if (path === '/api/v1/settings/connections/verify') {
        return Promise.resolve(ok({ ok: true, models_count: 10, message: 'Chiave valida · elenco dei modelli scaricato' }))
      }
      return Promise.resolve(ok(testSettings))
    }) as never)

    renderWizard('/impostazioni/configurazione?passo=1')
    const user = userEvent.setup()
    const keyInput = screen.getByLabelText('Chiave API')

    // Digitare non salva e non verifica
    await user.type(keyInput, 'sk-or-v1-abc')
    expect(post).not.toHaveBeenCalled()

    // Svuotare col cestino su campo pieno chiede conferma
    await user.click(screen.getByRole('button', { name: 'Svuota Chiave API' }))
    const confirmDialog = screen.getByRole('dialog', { name: 'Eliminare questa chiave?' })
    await user.click(within(confirmDialog).getByRole('button', { name: 'Elimina' }))
    expect(keyInput).toHaveValue('')

    // Incollare verifica senza salvare la connessione
    await user.click(keyInput)
    await user.paste('sk-or-v1-pasted-key')
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/settings/connections/verify', {
      body: { provider: 'openrouter', base_url: 'https://openrouter.ai/api/v1', api_key: 'sk-or-v1-pasted-key' },
    }))
    expect(await screen.findByTestId('key-verify-status')).toHaveTextContent('✓ Chiave valida · elenco dei modelli scaricato')
    expect(post).toHaveBeenCalledTimes(1)

    // Occhio mostra/nasconde
    const eye = screen.getByRole('button', { name: 'Mostra Chiave API' })
    expect(keyInput.className).toContain('secret-mask')
    await user.click(eye)
    expect(keyInput.className).not.toContain('secret-mask')

    // Continua salva la connessione
    await user.click(screen.getByRole('button', { name: 'Continua' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/settings/connections', {
      body: {
        name: 'OpenRouter',
        provider: 'openrouter',
        base_url: 'https://openrouter.ai/api/v1',
        api_keys: ['sk-or-v1-pasted-key'],
      },
    }))
  })
})

const unassignedSettings: Settings = {
  ...testSettings,
  phases: testSettings.phases.map((p) => ({ ...p, connection: null, model: null })),
}

const catalogModels = [
  { id: 'deepseek/deepseek-v4-flash', name: 'DeepSeek V4 Flash', prompt_price: 0.14, completion_price: 0.28, recommended: true },
  { id: 'google/gemini-2.5-flash', name: 'Gemini 2.5 Flash', prompt_price: 0.075, completion_price: 0.3, recommended: false },
  ...Array.from({ length: 55 }, (_, i) => ({
    id: `extra/model-${i + 1}`,
    name: `Extra Model ${i + 1}`,
    prompt_price: null,
    completion_price: null,
    recommended: false,
  })),
]

describe('SetupWizard: passo Modello e combobox', () => {
  it('combobox ARIA filtra, naviga da tastiera, ha autoComplete=off e non salva prima della scelta', async () => {
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/settings/connections/{name}/catalog') return Promise.resolve(ok(catalogModels))
      if (path === '/api/v1/settings/estimate') return Promise.resolve(ok({ cost_eur: 0.04, formatted: 'circa 0,04 € a lezione (stima)' }))
      return Promise.resolve(ok({}))
    }) as never)
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(testSettings))

    renderWizard('/impostazioni/configurazione?passo=2', unassignedSettings)
    const user = userEvent.setup()

    const combo = await screen.findByRole('combobox')
    expect(combo).toHaveAttribute('autocomplete', 'off')
    const continueBtn = screen.getByRole('button', { name: 'Continua' })
    expect(continueBtn).toBeDisabled()

    // Apre l'elenco: max 50 voci, Consigliato e prezzo visibili
    await user.click(combo)
    const listbox = screen.getByRole('listbox')
    expect(within(listbox).getAllByRole('option')).toHaveLength(50)
    expect(within(listbox).getByText('Consigliato')).toBeVisible()
    expect(within(listbox).getByText('$0.14 / M token')).toBeVisible()

    // Digitare filtra senza salvare nulla
    await user.type(combo, 'gemini')
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1)
    expect(put).not.toHaveBeenCalled()
    expect(continueBtn).toBeDisabled()

    // Esc chiude, ArrowDown riapre e Invio sceglie
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    await user.keyboard('{ArrowDown}{Enter}')
    expect(combo).toHaveValue('google/gemini-2.5-flash')
    expect(continueBtn).toBeEnabled()
    expect(await screen.findByTestId('wizard-cost-estimate')).toHaveTextContent('circa 0,04 € a lezione (stima)')

    // Nessun salvataggio prima di Continua
    expect(put).not.toHaveBeenCalled()

    await user.click(continueBtn)
    await waitFor(() => expect(put).toHaveBeenCalledTimes(6))
    expect((put.mock.calls as unknown as [string, { params: { path: { job: string } } }][]).map(([, options]) => options.params.path.job)).toEqual([
      'outline', 'rewrite', 'review', 'recall', 'enrichment_writer', 'enrichment_visualizer',
    ])
  })

  it('nasconde la stima se il prezzo manca, e i facoltativi non bloccano Continua', async () => {
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/settings/connections/{name}/catalog') return Promise.resolve(ok(catalogModels.slice(0, 2)))
      if (path === '/api/v1/settings/estimate') return Promise.resolve(ok({ cost_eur: null, formatted: 'stima non disponibile' }))
      return Promise.resolve(ok({}))
    }) as never)
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(testSettings))

    renderWizard('/impostazioni/configurazione?passo=2', unassignedSettings)
    const user = userEvent.setup()

    const combo = await screen.findByRole('combobox')
    await user.click(combo)
    await user.click(within(screen.getByRole('listbox')).getByText('DeepSeek V4 Flash'))

    expect(screen.getByRole('button', { name: 'Continua' })).toBeEnabled()
    expect(screen.queryByTestId('wizard-cost-estimate')).toBeNull()

    // Facoltativi presenti e non impostati, non bloccano
    const descRow = screen.getByTestId('optional-model-image_description')
    expect(descRow).toHaveTextContent('Non impostato')
    await user.click(within(descRow).getByRole('button', { name: 'Aggiungi' }))
    const optCombo = screen.getByRole('combobox', { name: 'Modello per Descrizione immagini' })
    await user.click(optCombo)
    await user.click(within(screen.getByRole('listbox')).getByText('Gemini 2.5 Flash'))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/phases/{job}', {
      params: { path: { job: 'image_description' } },
      body: { connection: 'locale', model: 'google/gemini-2.5-flash', batch: false },
    }))
  })

  it('in fallback su catalogo offline accetta un modello scritto a mano', async () => {
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/settings/connections/{name}/catalog') {
        return Promise.resolve(ok([{ id: 'test', name: 'test', prompt_price: null, completion_price: null, recommended: false }], { 'X-Catalog-Fallback': '1' }))
      }
      return Promise.resolve(ok({ cost_eur: null, formatted: 'stima non disponibile' }))
    }) as never)
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(testSettings))

    renderWizard('/impostazioni/configurazione?passo=2', unassignedSettings)
    const user = userEvent.setup()

    const combo = await screen.findByRole('combobox')
    await user.type(combo, 'custom/my-local-model')
    const continueBtn = screen.getByRole('button', { name: 'Continua' })
    expect(continueBtn).toBeEnabled()
    await user.click(continueBtn)
    await waitFor(() => expect(put).toHaveBeenCalledTimes(6))
  })
})

describe('SetupWizard: passo Pronto', () => {
  const readySettings: Settings = {
    ...testSettings,
    connections: [{
      name: 'OpenRouter',
      provider: 'openrouter',
      base_url: 'https://openrouter.ai/api/v1',
      models: ['deepseek/deepseek-v4-flash'],
      credentials: [{ name: 'or_1', set: true }],
      supports_batch: false,
    }],
    phases: testSettings.phases.map((p) =>
      ['image_description', 'enrichment_image'].includes(p.job)
        ? { ...p, connection: null, model: null }
        : { ...p, connection: 'OpenRouter', model: 'deepseek/deepseek-v4-flash' },
    ),
  }

  it('mostra le due schede, il collegamento a Telegram, il riepilogo e segna la guida completata su ogni uscita', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(readySettings))
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ lesson_id: 42, materia: 'ESEMPIO', titolo: 'Introduzione a RT' }))
    const openNewLesson = vi.fn()

    renderWizard('/impostazioni/configurazione?passo=3', readySettings, openNewLesson)
    const user = userEvent.setup()

    expect(screen.getByRole('heading', { name: 'RT è pronto' })).toBeVisible()
    expect(screen.getByRole('button', { name: /Prova la lezione di esempio/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Crea la tua prima lezione/ })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Collega Telegram →' })).toHaveAttribute('href', '/impostazioni/telegram/collega')

    const summary = screen.getByTestId('wizard-summary')
    expect(summary).toHaveTextContent('✓ Connessione — OpenRouter · 1 chiave')
    expect(summary).toHaveTextContent('✓ Modello — deepseek/deepseek-v4-flash')
    expect(summary).toHaveTextContent('– Immagini (facoltativo) — Aggiungi')
    expect(within(summary).getByRole('link', { name: 'Aggiungi' })).toHaveAttribute('href', '/impostazioni/modelli')

    // Uscita 1: Prova la lezione di esempio
    await user.click(screen.getByRole('button', { name: /Prova la lezione di esempio/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/sample'))
    expect(put).toHaveBeenCalledWith('/api/v1/settings/notices', { body: { notice: 'setup_wizard', dismissed: true } })
    expect(await screen.findByText('Lezione di esempio aperta')).toBeVisible()

    // Uscita 2: Crea la tua prima lezione
    cleanup()
    put.mockClear()
    renderWizard('/impostazioni/configurazione?passo=3', readySettings, openNewLesson)
    await user.click(screen.getByRole('button', { name: /Crea la tua prima lezione/ }))
    expect(put).toHaveBeenCalledWith('/api/v1/settings/notices', { body: { notice: 'setup_wizard', dismissed: true } })
    expect(openNewLesson).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Elenco lezioni')).toBeVisible()

    // Uscita 3: Vai alle lezioni
    cleanup()
    put.mockClear()
    renderWizard('/impostazioni/configurazione?passo=3', readySettings, openNewLesson)
    await user.click(screen.getByRole('button', { name: 'Vai alle lezioni' }))
    expect(put).toHaveBeenCalledWith('/api/v1/settings/notices', { body: { notice: 'setup_wizard', dismissed: true } })
    expect(await screen.findByText('Elenco lezioni')).toBeVisible()
  })

  it('avvia il download del modello di trascrizione al passo Modello e mostra la barra', async () => {
    const comp = {
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
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/components') return Promise.resolve(ok([comp]))
      if (path === '/api/v1/settings/connections/{name}/catalog') return Promise.resolve(ok(catalogModels.slice(0, 2)))
      return Promise.resolve(ok({}))
    }) as never)
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...comp, state: 'downloading' }))

    renderWizard('/impostazioni/configurazione?passo=2', unassignedSettings)
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', {
        params: { path: { component_id: 'transcription' } },
      }),
    )
    expect(await screen.findByTestId('wizard-transcription-download')).toHaveTextContent('Trascrizione')
    expect(screen.getByTestId('wizard-transcription-download')).toHaveTextContent('Modello di trascrizione')
  })

  it('sul Mac scheda Trascrizione avvia macparakeet e «Usa un altro motore» apre la scelta', async () => {
    const macSettings: Settings = {
      ...unassignedSettings,
      transcription: {
        ...unassignedSettings.transcription,
        engine: 'macparakeet',
        recommended: 'macparakeet',
        effective_engine: 'macparakeet',
        macparakeet_available: true,
      },
    }
    const macComp = {
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
    const onnxComp = {
      id: 'transcription',
      name: 'Modello di trascrizione',
      description: "necessario per trascrivere l'audio",
      detail: 'Parakeet ONNX + VAD',
      required: false,
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
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/components') return Promise.resolve(ok([macComp, onnxComp]))
      if (path === '/api/v1/settings/connections/{name}/catalog') return Promise.resolve(ok(catalogModels.slice(0, 2)))
      return Promise.resolve(ok({}))
    }) as never)
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...macComp, state: 'downloading', percent: 25, eta_label: 'circa 2 min' }))
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(macSettings))

    renderWizard('/impostazioni/configurazione?passo=2', macSettings)
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', {
        params: { path: { component_id: 'macparakeet' } },
      }),
    )
    const card = await screen.findByTestId('wizard-transcription-download')
    expect(card).toHaveTextContent('Trascrizione')
    expect(card).toHaveTextContent('Motore di trascrizione')

    const user = userEvent.setup()
    await user.click(within(card).getByRole('button', { name: 'Usa un altro motore' }))
    expect(within(card).getByRole('radio', { name: 'macparakeet · consigliato' })).toBeChecked()
    expect(within(card).getByRole('radio', { name: 'Parakeet ONNX' })).toBeVisible()
    expect(within(card).getByRole('radio', { name: 'Server OpenAI-compatible' })).toBeVisible()

    await user.click(within(card).getByRole('radio', { name: 'Parakeet ONNX' }))
    expect(put).toHaveBeenCalledWith('/api/v1/settings/transcription', {
      body: expect.objectContaining({ engine: 'parakeet' }),
    })
  })
})
