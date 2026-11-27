import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
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

function renderWizard(entry: string, settings: Settings = emptySettings) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/impostazioni/configurazione" element={<SetupWizard settings={settings} />} />
          <Route path="/" element={<p>Elenco lezioni</p>} />
        </Routes>
      </MemoryRouter>
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

it('il modello comune non assegna le fasi delle immagini e resta nel passo Modelli', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: testSettings, response: new Response('{}', { status: 200 }) } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/impostazioni/configurazione?passo=2']}><SetupWizard settings={testSettings} /></MemoryRouter></QueryClientProvider>)
  const form = screen.getByRole('form', { name: 'Stesso modello per tutte le fasi' })
  await userEvent.click(within(form).getByRole('button', { name: 'Usa per tutte le fasi' }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(6))
  expect((put.mock.calls as unknown as [string, { params: { path: { job: string } } }][]).map(([, options]) => options.params.path.job)).toEqual(['outline', 'rewrite', 'review', 'recall', 'enrichment_writer', 'enrichment_visualizer'])
  expect(screen.getByText(/Descrizione immagini e generazione immagini richiedono modelli dedicati/)).toBeVisible()
  expect(screen.getAllByTestId('phase-row')).toHaveLength(2)
})
