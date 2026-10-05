import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { PricingSection } from './keys'
import { testSettings } from './testSettings'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('salva i costi della connessione conservando quelli degli altri modelli e provider', async () => {
  const settings = { ...testSettings, pricing: { openai_compatible: { test: { input_per_million: 1, output_per_million: 2 }, altro: { input_per_million: 3, output_per_million: 4 } }, openrouter: { remoto: { input_per_million: 5, output_per_million: 6 } } },
    connections: [...testSettings.connections, { ...testSettings.connections[0], name: 'seconda', models: ['altro'] }] }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['settings'], settings)
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: settings, response: new Response('{}', { status: 200 }) } as never)
  render(<QueryClientProvider client={client}><PricingSection settings={settings} connection={settings.connections[0]} /></QueryClientProvider>)
  expect(screen.getAllByTestId('pricing-row')).toHaveLength(1)
  await userEvent.clear(screen.getByLabelText('IN 1'))
  await userEvent.type(screen.getByLabelText('IN 1'), '0,15')
  await userEvent.click(screen.getByRole('button', { name: 'Salva costi' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/pricing', { body: { ...settings.pricing, openai_compatible: { altro: settings.pricing.openai_compatible.altro, test: { input_per_million: 0.15, output_per_million: 2 } } } }))
})
