import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { testSettings } from './testSettings'
import { SetupWizard } from './wizard'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('il modello comune non assegna le fasi delle immagini e resta nel passo Modelli', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: testSettings, response: new Response('{}', { status: 200 }) } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/impostazioni/configurazione?passo=2']}><SetupWizard settings={testSettings} /></MemoryRouter></QueryClientProvider>)
  const form = screen.getByRole('form', { name: 'Stesso modello per tutte le fasi' })
  await userEvent.click(within(form).getByRole('button', { name: 'Usa per tutte le fasi' }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(6))
  expect((put.mock.calls as unknown as [string, { params: { path: { job: string } } }][]).map(([, options]) => options.params.path.job)).toEqual(['outline', 'rewrite', 'review', 'recall', 'enrichment_writer', 'enrichment_visualizer'])
  expect(screen.getByText(/Descrizione immagini e generazione immagini richiedono modelli dedicati/)).toBeVisible()
  expect(screen.getAllByTestId('phase-row')).toHaveLength(2)
})
