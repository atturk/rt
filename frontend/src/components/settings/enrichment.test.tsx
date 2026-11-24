import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { EnrichmentSettingsSection } from './enrichment'
import { enrichmentSettings, testSettings } from './testSettings'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('le impostazioni dell’arricchimento conservano tetto e soglia senza modalità o modelli e salvano in automatico', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(enrichmentSettings))
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(enrichmentSettings))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><EnrichmentSettingsSection settings={testSettings} /></QueryClientProvider>)
  await screen.findByLabelText('Numero massimo')
  expect(screen.queryByLabelText('Modalità dell’arricchimento')).toBeNull()
  expect(screen.queryByLabelText('Modello decisionale')).toBeNull()
  const utility = screen.getByLabelText('Utilità minima (0–1)')
  fireEvent.change(utility, { target: { value: '0.65' } })
  fireEvent.blur(utility)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/enrichment', {
    body: expect.objectContaining({ utility_threshold: 0.65 }),
  }))
})
