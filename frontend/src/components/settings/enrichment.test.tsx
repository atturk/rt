import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { EnrichmentSettingsSection } from './enrichment'
import { enrichmentSettings, testSettings } from './testSettings'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('le impostazioni dell’arricchimento conservano tetto e soglia senza modalità o modelli', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(enrichmentSettings))
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(enrichmentSettings))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><EnrichmentSettingsSection settings={testSettings} /></QueryClientProvider>)
  await screen.findByLabelText('Numero massimo')
  expect(screen.queryByLabelText('Modalità dell’arricchimento')).toBeNull()
  expect(screen.queryByLabelText('Modello decisionale')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Salva arricchimento' }))
  await waitFor(() => expect(put).toHaveBeenCalled())
})
