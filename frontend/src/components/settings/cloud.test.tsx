import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { CloudPanel } from './cloud'
import { testSettings } from './testSettings'
import { SetupWizard } from './wizard'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const ok = (data: unknown) => ({ data, response: new Response('{}', { status: 200 }) }) as never
const base = { available: true, logged_in: false, email: null, subscription: null, balance: null, connection: false }
const active = {
  ...base, logged_in: true, email: 'studente@example.com', connection: true,
  subscription: { status: 'active', plan: 'base', current_period_end: null, monthly_quota_usd: 1.44 },
  balance: { limit_usd: 1.44, usage_usd: 0.4, remaining_usd: 1.04 },
}

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

it('accesso con email e codice', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(base))
  const post = vi.spyOn(api, 'POST').mockImplementation(((path: string) =>
    Promise.resolve(ok(path.endsWith('/verify') ? { ...base, logged_in: true, email: 'studente@example.com', subscription: { status: 'none', monthly_quota_usd: 0 } } : null))) as never)
  wrap(<CloudPanel />)
  await userEvent.type(await screen.findByLabelText('Email'), 'studente@example.com')
  await userEvent.click(screen.getByRole('button', { name: 'Mandami il codice' }))
  await userEvent.type(await screen.findByLabelText('Codice ricevuto per email'), '123456')
  await userEvent.click(screen.getByRole('button', { name: 'Accedi' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/cloud/login/verify', { body: { email: 'studente@example.com', code: '123456' } }))
  expect(await screen.findByRole('button', { name: 'Abbonati' })).toBeVisible()
})

it('con l\'abbonamento attivo mostra il credito rimasto', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(active))
  wrap(<CloudPanel />)
  expect(await screen.findByTestId('cloud-balance')).toHaveTextContent('Credito rimasto: 1.04 $')
  expect(screen.getByRole('progressbar', { name: 'Credito rimasto' })).toHaveAttribute('aria-valuenow', '72')
})

it('la configurazione guidata offre la modalità facilitata solo se RT Cloud esiste', async () => {
  const get = vi.spyOn(api, 'GET').mockResolvedValue(ok(base))
  const settings = { ...testSettings, connections: [] }
  wrap(<SetupWizard settings={settings} />)
  await userEvent.click(await screen.findByLabelText(/Facilitata/))
  expect(await screen.findByLabelText('Email')).toBeVisible()
  cleanup()
  get.mockResolvedValue(ok({ ...base, available: false }))
  wrap(<SetupWizard settings={settings} />)
  await waitFor(() => expect(get).toHaveBeenCalled())
  expect(screen.queryByLabelText(/Facilitata/)).toBeNull()
})
