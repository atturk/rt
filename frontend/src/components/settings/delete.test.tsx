import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { InfoSection } from './info'
import { SecretsSection } from './keys'
import { ConnectionsSection } from './models'

const SETTINGS = {
  connections: [
    { name: 'openrouter', provider: 'openrouter', base_url: 'https://openrouter.ai/api/v1', models: ['m/a'], credentials: [{ name: 'openrouter', set: true }] },
    { name: 'google_1', provider: 'google', base_url: 'https://g', models: [], credentials: [{ name: 'google_1', set: false }] },
  ],
  credentials: [
    { name: 'openrouter', provider: 'openrouter', env_var: 'OPENROUTER_API_KEY', set: true },
    { name: 'google_1', provider: 'google', env_var: 'RT_GOOGLE_1_API_KEY', set: false },
  ],
  phases: [],
  telegram: { bot_token_set: true },
  transcription: { api_key_set: false },
  secrets_encrypted: true,
} as unknown as Settings

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) }) as never

afterEach(() => vi.restoreAllMocks())

describe('Connessioni: elimina con Option', () => {
  it('il cestino compare con Option, chiede conferma e mostra il 409 della connessione in uso', async () => {
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue({
      data: undefined,
      error: { error: { code: 'connection_in_use', message: 'La connessione «openrouter» è ancora usata da: Review (primaria).' } },
      response: new Response('{}', { status: 409 }),
    } as never)
    renderWith(<ConnectionsSection settings={SETTINGS} />)
    const user = userEvent.setup()
    const card = screen.getByRole('group', { name: 'Connessione openrouter' })
    const trash = within(card).getByRole('button', { name: 'Elimina la connessione openrouter' })
    expect(trash.className).toMatch(/md:opacity-0/)
    fireEvent.keyDown(window, { key: 'Alt' })
    expect(trash.className).not.toMatch(/md:opacity-0/)
    fireEvent.keyUp(window, { key: 'Alt' })
    expect(trash.className).toMatch(/md:opacity-0/)

    await user.click(trash)
    expect(screen.getByText(/Eliminare la connessione «openrouter» con i suoi modelli e la sua chiave/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Elimina' }))
    expect(del).toHaveBeenCalledWith('/api/v1/settings/connections/{name}', { params: { path: { name: 'openrouter' } } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Review (primaria)')
  })
})

describe('Chiavi: Prova diventa Elimina con Option', () => {
  it('solo per le chiavi impostate, con conferma', async () => {
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok({ name: 'OPENROUTER_API_KEY', set: false, removed_from: ['store'] }))
    vi.spyOn(api, 'GET').mockResolvedValue(ok(SETTINGS))
    renderWith(<SecretsSection settings={SETTINGS} />)
    const user = userEvent.setup()
    const row = (name: string) => screen.getAllByTestId('secret-row').find((r) => r.dataset.name === name)!
    expect(within(row('OPENROUTER_API_KEY')).getByRole('button', { name: 'Prova' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Elimina/ })).toBeNull()

    fireEvent.keyDown(window, { key: 'Alt' })
    const openrouter = row('OPENROUTER_API_KEY')
    expect(within(openrouter).queryByRole('button', { name: 'Prova' })).toBeNull()
    expect(within(row('RT_GOOGLE_1_API_KEY')).getByRole('button', { name: 'Prova' })).toBeInTheDocument() // mancante
    expect(within(row('RT_TELEGRAM_BOT_TOKEN')).getByRole('button', { name: /^Elimina/ })).toBeInTheDocument()
    expect(within(row('RT_STT_API_KEY')).queryByRole('button', { name: /^Elimina/ })).toBeNull()

    await user.click(within(openrouter).getByRole('button', { name: /^Elimina openrouter/ }))
    fireEvent.keyUp(window, { key: 'Alt' })
    const dialog = screen.getByText(/Eliminare la chiave di «openrouter/).closest('dialog')!
    await user.click(within(dialog).getByRole('button', { name: 'Elimina' }))
    expect(del).toHaveBeenCalledWith('/api/v1/secrets/{name}', { params: { path: { name: 'OPENROUTER_API_KEY' } } })
    expect(await screen.findByText('Chiave eliminata.')).toBeInTheDocument()
  })
})

describe('Info', () => {
  it('mostra versione, canale e cartelle', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({
      version: '4.1.0b3', prerelease: true, update_channel: 'beta', install_dir: '/opt/rt',
      data_dir: '/Users/a/.rt', config_dir: '/Users/a/.rt/config', python_version: '3.11.9', platform: 'Darwin 24.0 (arm64)',
    }))
    renderWith(<InfoSection />)
    const info = await screen.findByTestId('system-info')
    expect(info).toHaveTextContent('4.1.0b3')
    expect(info).toHaveTextContent('Beta (anche le versioni di prova)')
    expect(info).toHaveTextContent('/Users/a/.rt')
    expect(info).toHaveTextContent('3.11.9')
  })
})
