import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { DEVICE_ORIGIN_KEY } from '@/lib/deviceLogin'
import { DeviceAccessSection } from './device-access'

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DeviceAccessSection />
    </QueryClientProvider>,
  )
}

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) }) as never

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe("Accesso da un altro dispositivo", () => {
  it("crea il QR con il codice monouso sull'indirizzo della tailnet e lo ricorda", async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ url: 'http://127.0.0.1:8765/login?code=abc123', expires_in: 300 }))
    renderSection()
    const user = userEvent.setup()
    const button = screen.getByRole('button', { name: 'Crea QR di accesso' })
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText("Indirizzo di RT per l'altro dispositivo"), 'mac.tail1234.ts.net')
    await user.click(button)
    expect(post).toHaveBeenCalledWith('/api/v1/auth/login-link')
    expect(await screen.findByTestId('device-login-url')).toHaveTextContent('https://mac.tail1234.ts.net/login?code=abc123')
    expect(screen.getByRole('img', { name: 'QR del link di accesso' })).toBeInTheDocument()
    expect(screen.getByText(/Scade tra 5:00/)).toBeInTheDocument()
    expect(localStorage.getItem(DEVICE_ORIGIN_KEY)).toBe('https://mac.tail1234.ts.net')
  })

  it("propone da solo il nome del Mac nella tailnet e lo usa per il QR", async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({ origin: 'https://air.tail1234.ts.net', serve: true, funnel: false }))
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ url: 'http://127.0.0.1:8765/login?code=xyz', expires_in: 300 }))
    localStorage.setItem(DEVICE_ORIGIN_KEY, 'https://100.72.84.124')
    renderSection()
    const user = userEvent.setup()
    const input = screen.getByLabelText("Indirizzo di RT per l'altro dispositivo")
    await waitFor(() => expect(input).toHaveValue('https://air.tail1234.ts.net'))
    await user.click(screen.getByRole('button', { name: 'Crea QR di accesso' }))
    expect(post).toHaveBeenCalledWith('/api/v1/auth/login-link')
    expect(await screen.findByTestId('device-login-url')).toHaveTextContent('https://air.tail1234.ts.net/login?code=xyz')
  })

  it("avvisa se l'indirizzo è un IP in https o se Tailscale Serve non è attivo", async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(ok({ origin: 'https://air.tail1234.ts.net', serve: false, funnel: false }))
    renderSection()
    const user = userEvent.setup()
    const input = screen.getByLabelText("Indirizzo di RT per l'altro dispositivo")
    await waitFor(() => expect(input).toHaveValue('https://air.tail1234.ts.net'))
    expect(screen.getByText(/Tailscale Serve non è attivo/)).toBeInTheDocument()
    await user.clear(input)
    await user.type(input, '100.72.84.124')
    expect(screen.getByText(/il certificato di Tailscale vale solo per il nome del computer/)).toBeInTheDocument()
  })

  it("avvisa se l'indirizzo è quello locale del Mac", async () => {
    renderSection()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Indirizzo di RT per l'altro dispositivo"), 'http://127.0.0.1:8765')
    expect(screen.getByText(/raggiunge solo questo computer/)).toBeInTheDocument()
  })

  it("gestisce la chiave di sola lettura, il prompt per gli agenti e la revoca", async () => {
    let keyInfo: { configured: boolean; key?: string | null; key_preview?: string | null; base_url?: string | null; created_at?: string | null } = {
      configured: false,
      key: null,
      base_url: 'http://127.0.0.1:8765/api/v1/readonly',
    }

    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/settings/readonly-key') {
        return Promise.resolve(ok(keyInfo))
      }
      return Promise.resolve(ok({}))
    })
    const post = vi.spyOn(api, 'POST').mockImplementation((path: string) => {
      if (path === '/api/v1/settings/readonly-key') {
        keyInfo = {
          configured: true,
          key: 'rt_ro_secret123',
          key_preview: 'rt_ro_se…c123',
          base_url: 'http://127.0.0.1:8765/api/v1/readonly',
          created_at: '2026-10-12T22:00:00Z',
        }
        return Promise.resolve(ok({ key: 'rt_ro_secret123', created_at: '2026-10-12T22:00:00Z', key_preview: 'rt_ro_se…c123' }))
      }
      return Promise.resolve(ok({}))
    })
    const del = vi.spyOn(api, 'DELETE').mockImplementation((path: string) => {
      if (path === '/api/v1/settings/readonly-key') {
        keyInfo = { configured: false, key: null, base_url: 'http://127.0.0.1:8765/api/v1/readonly' }
        return Promise.resolve(ok({ ok: true }))
      }
      return Promise.resolve(ok({}))
    })

    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    renderSection()

    // Senza chiave: nessuna chiave visibile, nessun prompt, solo "Crea chiave"
    expect(await screen.findByTestId('readonly-key-status')).toHaveTextContent('Non configurata')
    expect(screen.queryByTestId('readonly-key-value')).toBeNull()
    expect(screen.queryByTestId('readonly-agent-prompt-box')).toBeNull()
    expect(screen.getByRole('button', { name: 'Crea chiave' })).toBeInTheDocument()

    // Clicca Crea chiave
    await user.click(screen.getByRole('button', { name: 'Crea chiave' }))
    expect(post).toHaveBeenCalledWith('/api/v1/settings/readonly-key')

    // Con chiave attiva: la chiave si vede e il prompt contiene base e chiave
    const keyInput = await screen.findByTestId('readonly-key-value')
    expect(keyInput).toHaveValue('rt_ro_secret123')

    const promptBox = await screen.findByTestId('readonly-agent-prompt-box')
    expect(promptBox).toBeInTheDocument()
    const promptText = screen.getByTestId('agent-prompt-text').textContent ?? ''
    expect(promptText).toContain('http://127.0.0.1:8765/api/v1/readonly')
    expect(promptText).toContain('Authorization: Bearer rt_ro_secret123')
    expect(promptText).toContain('Puoi leggere le mie lezioni universitarie da RT')

    // Copia prompt copia il testo completo
    const copyPromptBtn = screen.getByTestId('copy-agent-prompt')
    await user.click(copyPromptBtn)
    expect(writeText).toHaveBeenCalledWith(promptText)

    // Clicca Revoca
    const revokeBtn = await screen.findByTestId('btn-revoke-readonly-key')
    await user.click(revokeBtn)
    expect(screen.getByText(/Revocare la chiave di sola lettura\?/)).toBeInTheDocument()
    const dialogConfirm = screen.getAllByRole('button', { name: 'Revoca' }).slice(-1)[0]
    await user.click(dialogConfirm)
    expect(del).toHaveBeenCalledWith('/api/v1/settings/readonly-key')

    // Dopo la revoca, chiave e prompt scompaiono e torna "Crea chiave"
    await waitFor(() => {
      expect(screen.queryByTestId('readonly-key-value')).toBeNull()
      expect(screen.queryByTestId('readonly-agent-prompt-box')).toBeNull()
      expect(screen.getByRole('button', { name: 'Crea chiave' })).toBeInTheDocument()
    })
  })
})
