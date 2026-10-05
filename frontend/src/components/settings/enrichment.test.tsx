import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { EnrichmentSettingsSection } from './enrichment'
import { enrichmentSettings, testSettings } from './testSettings'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it.each([['Disattivato', 'disabled', false], ['Manuale', 'manual', false], ['Automatico', 'automatic', true]])('un solo controllo %s salva mode e automatic coerenti', async (label, mode, automatic) => {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(enrichmentSettings))
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok({ ...enrichmentSettings, mode, automatic }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><EnrichmentSettingsSection settings={testSettings} /></QueryClientProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Modalità dell’arricchimento' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: label as string }))
  expect(screen.queryByText(/Analizza anche nella pipeline/)).toBeNull()
  expect(screen.queryByLabelText('Modello decisionale')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Salva arricchimento' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/enrichment', { body: { ...enrichmentSettings, mode, automatic } }))
})
