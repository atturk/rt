import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { TelegramConnectScreen, TelegramSection, NotificationsCard } from './telegram'
import { testSettings } from './testSettings'

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) }) as never

function renderSection(telegram: Settings['telegram']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TelegramSection settings={{ ...testSettings, telegram }} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Telegram: notifiche nella chat personale', () => {
  it('spento: solo l\'interruttore', () => {
    renderSection({ enabled: false, bot_token_set: false, chat_id_set: false })
    expect(screen.getByLabelText('Ricevi le notifiche su Telegram')).not.toBeChecked()
    expect(screen.queryByRole('button', { name: /^Collega$/ })).toBeNull()
  })

  it('primo collegamento in Impostazioni › Telegram usa TelegramConnectScreen', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(testSettings))
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ found: true, name: 'Ada', message: 'Chat collegata: Ada.' }))
    vi.spyOn(api, 'GET').mockResolvedValue(ok(testSettings))
    renderSection({ enabled: true, bot_token_set: false, chat_id_set: false })
    const user = userEvent.setup()

    expect(screen.getByRole('heading', { name: 'Usa RT anche da Telegram' })).toBeVisible()
    const connect = screen.getByRole('button', { name: 'Collega' })
    expect(connect).toBeDisabled()

    await user.type(screen.getByLabelText('Token del bot'), '123:abc')
    await user.click(connect)
    expect(put).toHaveBeenCalledWith('/api/v1/settings/telegram', { body: { bot_token: '123:abc' } })
    expect(post).toHaveBeenCalledWith('/api/v1/settings/telegram/chat', { body: { bot_token: '123:abc' } })
  })

  it('con token e chat salvati la prova è attiva', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ok: true, message: 'Messaggio di prova inviato: controlla Telegram.' }))
    vi.spyOn(api, 'GET').mockResolvedValue(ok([]))
    renderSection({ enabled: true, bot_token_set: true, chat_id_set: true, bot_token_preview: '123…abc', chat_id_preview: '55…23' })
    const user = userEvent.setup()
    expect(screen.getByTestId('telegram-chat')).toHaveTextContent('Chat collegata: 55…23')
    await user.click(screen.getByRole('button', { name: /messaggio di prova/ }))
    expect(post).toHaveBeenCalledWith('/api/v1/settings/telegram/test')
    expect(await screen.findByTestId('telegram-test-result')).toHaveTextContent('controlla Telegram')
  })

  it('interruttori degli eventi: salva le scelte su PUT /settings/telegram/notify', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok({
      ...testSettings,
      telegram: { ...testSettings.telegram, enabled: true, notify: { ...testSettings.telegram.notify, errore: false } },
    }))
    vi.spyOn(api, 'GET').mockResolvedValue(ok(testSettings))
    renderSection({ enabled: true, bot_token_set: true, chat_id_set: true, notify: { lezione_pronta: true, verifica_pronta: true, errore: true, scaletta_da_approvare: true, issue_da_decidere: true } })
    const user = userEvent.setup()

    expect(screen.getByText('Ricevi una notifica quando…')).toBeInTheDocument()
    const errorSwitch = screen.getByRole('switch', { name: 'Una lavorazione non riesce' })
    expect(errorSwitch).toHaveAttribute('aria-checked', 'true')
    await user.click(errorSwitch)
    expect(put).toHaveBeenCalledWith('/api/v1/settings/telegram/notify', {
      body: {
        notify: {
          lezione_pronta: true,
          verifica_pronta: true,
          errore: false,
          scaletta_da_approvare: true,
          issue_da_decidere: true,
        },
      },
    })
  })

  it('storico notifiche: cestino svuota l’elenco in RT e mostra Nessuna notifica', async () => {
    let list = [
      { sent_at: '2026-11-24T20:00:00Z', kind: 'verifica_pronta', text: 'Verifica completata · Lipidi', ok: true },
    ]
    vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(ok(list))) as never)
    const del = vi.spyOn(api, 'DELETE').mockImplementation((() => {
      list = []
      return Promise.resolve(ok({ cleared: 1 }))
    }) as never)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NotificationsCard />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()
    expect(await screen.findByText('Verifica completata · Lipidi')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: "Svuota l'elenco" }))
    expect(del).toHaveBeenCalledWith('/api/v1/telegram/notifications')
    expect(await screen.findByText('Nessuna notifica.')).toBeInTheDocument()
  })
})

describe('TelegramConnectScreen', () => {
  function LocationProbe() {
    const loc = useLocation()
    return <span data-testid="loc">{loc.pathname}{loc.search}</span>
  }

  function renderConnect(state?: { from?: string }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[{ pathname: '/impostazioni/telegram/collega', state }]}>
          <Routes>
            <Route path="/impostazioni/telegram/collega" element={<><LocationProbe /><TelegramConnectScreen settings={testSettings} /></>} />
            <Route path="/impostazioni/configurazione" element={<><LocationProbe /><p>Wizard pronto</p></>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('Annulla torna alla pagina di provenienza', async () => {
    renderConnect({ from: '/impostazioni/configurazione?passo=3' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Annulla' }))
    expect(await screen.findByTestId('loc')).toHaveTextContent('/impostazioni/configurazione?passo=3')
  })

  it('Collega chiama le due API e, se la chat non si trova, mostra il fallback manuale Chat ID', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(testSettings))
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ found: false, message: 'Nessun messaggio' }))
    renderConnect({ from: '/impostazioni/configurazione?passo=3' })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Token del bot'), '999:tok')
    await user.click(screen.getByRole('button', { name: 'Collega' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/telegram', { body: { bot_token: '999:tok' } }))
    expect(post).toHaveBeenCalledWith('/api/v1/settings/telegram/chat', { body: { bot_token: '999:tok' } })
    expect(await screen.findByTestId('telegram-chat-not-found')).toHaveTextContent('Non trovo il tuo messaggio: scrivi qualcosa al bot e riprova')

    await user.click(screen.getByRole('button', { name: "Inserisci l'ID a mano" }))
    await user.type(screen.getByLabelText('Chat ID'), '5551234')
    await user.click(screen.getByRole('button', { name: 'Salva Chat ID' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/telegram', { body: { bot_token: '999:tok', chat_id: '5551234' } }))
    expect(await screen.findByTestId('loc')).toHaveTextContent('/impostazioni/configurazione?passo=3')
  })
})
