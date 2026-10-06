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
    expect(screen.getByText(/il certificato di Tailscale vale solo per il nome del Mac/)).toBeInTheDocument()
  })

  it("avvisa se l'indirizzo è quello locale del Mac", async () => {
    renderSection()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Indirizzo di RT per l'altro dispositivo"), 'http://127.0.0.1:8765')
    expect(screen.getByText(/raggiunge solo il Mac stesso/)).toBeInTheDocument()
  })
})
