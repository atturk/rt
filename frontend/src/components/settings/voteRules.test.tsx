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
it('mostra la regola chiusa con il riepilogo voti, la apre al clic e salva le regole modificate al blur', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(result(data) as never)
  setup()
  const disclosure = await screen.findByRole('button', { name: /Mirata · Medicina/ })
  expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  expect(disclosure).toHaveTextContent('7 voti')
  expect(screen.queryByLabelText('Mirata · Medicina')).toBeNull()

  fireEvent.click(disclosure)
  expect(disclosure).toHaveAttribute('aria-expanded', 'true')
  const field = screen.getByLabelText('Mirata · Medicina')
  fireEvent.change(field, { target: { value: 'Evita le date\nChiedi il ragionamento' } })
  fireEvent.blur(field)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/recall-rules', { body: { type: 'mirata', subject: 'Medicina', rules: ['Evita le date', 'Chiedi il ragionamento'] } }))
})
it('gli interruttori sono accesi e Rigenera accoda un job', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(result(data) as never)
  const post = vi.spyOn(api, 'POST').mockResolvedValue(result({ job_id: 'rules-job' }) as never)
  setup()
  const votesSwitch = await screen.findByRole('switch', { name: 'Usa i voti per migliorare le domande' })
  const presaveSwitch = screen.getByRole('switch', { name: 'Controlla le domande prima di salvarle' })
  expect(votesSwitch).toHaveAttribute('aria-checked', 'true')
  expect(presaveSwitch).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(votesSwitch)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/recall-votes', { body: { votes_enabled: false, presave_check: true } }))
  fireEvent.click(screen.getByRole('button', { name: /Mirata · Medicina/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Rigenera' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/settings/recall-rules/update', { body: { type: 'mirata', subject: 'Medicina', mock: false } }))
})
