import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { TelegramSection } from './telegram'
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

afterEach(() => vi.restoreAllMocks())

describe('Telegram: notifiche nella chat personale', () => {
  it('spento: solo l\'interruttore', () => {
    renderSection({ enabled: false, bot_token_set: false, chat_id_set: false })
    expect(screen.getByLabelText('Ricevi le notifiche su Telegram')).not.toBeChecked()
    expect(screen.queryByRole('button', { name: /Collega la chat/ })).toBeNull()
  })

  it('collega la chat con il token incollato e manda la prova', async () => {
    const post = vi.spyOn(api, 'POST').mockImplementation(((path: string) =>
      Promise.resolve(
        path === '/api/v1/settings/telegram/chat'
          ? ok({ found: true, name: 'Ada', message: 'Chat collegata: Ada.' })
          : ok({ ok: true, message: 'Messaggio di prova inviato: controlla Telegram.' }),
      )) as never)
    vi.spyOn(api, 'GET').mockResolvedValue(ok(testSettings))
    renderSection({ enabled: true, bot_token_set: false, chat_id_set: false })
    const user = userEvent.setup()

    const connect = screen.getByRole('button', { name: /Collega la chat/ })
    expect(connect).toBeDisabled()
    expect(screen.getByRole('button', { name: /messaggio di prova/ })).toBeDisabled()
    expect(screen.getByTestId('telegram-chat')).toHaveTextContent('Nessuna chat collegata.')

    await user.type(screen.getByLabelText('Token del bot'), '123:abc')
    await user.click(connect)
    expect(post).toHaveBeenCalledWith('/api/v1/settings/telegram/chat', { body: { bot_token: '123:abc' } })
    expect(await screen.findByTestId('telegram-chat-result')).toHaveTextContent('Chat collegata: Ada.')
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
})
