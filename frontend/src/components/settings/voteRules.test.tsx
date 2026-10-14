import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { api } from '@/api/client'
import { VoteRulesSettings } from './questions'

const data = { votes_enabled: true, presave_check: true, groups: [{ type: 'mirata', subject: 'Medicina', votes: 7, rules: ['Evita date storiche'], updated_at: '2026-10-14T20:00:00Z' }] }
const result = (value: unknown) => ({ data: value, response: new Response('{}', { status: 200 }) })
afterEach(() => vi.restoreAllMocks())
function setup() {
  vi.spyOn(api, 'GET').mockResolvedValue(result(data) as never)
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><VoteRulesSettings /></QueryClientProvider>)
}
it('mostra materia, voti, data e salva le regole modificate a mano', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(result(data) as never)
  setup()
  const field = await screen.findByLabelText('mirata · Medicina')
  expect(screen.getByText(/7 voti/)).toBeInTheDocument()
  fireEvent.change(field, { target: { value: 'Evita le date\nChiedi il ragionamento' } })
  fireEvent.blur(field)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/recall-rules', { body: { type: 'mirata', subject: 'Medicina', rules: ['Evita le date', 'Chiedi il ragionamento'] } }))
})
it('gli interruttori sono accesi e Aggiorna ora accoda un job', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(result(data) as never)
  const post = vi.spyOn(api, 'POST').mockResolvedValue(result({ job_id: 'rules-job' }) as never)
  setup()
  await screen.findByLabelText('mirata · Medicina')
  expect(screen.getByRole('switch', { name: 'Voti' })).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('switch', { name: 'Controllo prima di salvare' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(screen.getByRole('switch', { name: 'Voti' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/recall-votes', { body: { votes_enabled: false, presave_check: true } }))
  fireEvent.click(screen.getByRole('button', { name: 'Aggiorna ora' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/settings/recall-rules/update', { body: { type: 'mirata', subject: 'Medicina' } }))
})
