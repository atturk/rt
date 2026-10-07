import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { EmptyGeneration } from './EmptyGeneration'

const state = vi.hoisted(() => ({ suggestions: true, mutate: vi.fn(), failed: false }))
vi.mock('@/api/recall', () => ({
  recallKeys: { all: () => ['recall'] },
  useStudyLesson: () => ({ data: { suggestions: state.suggestions } }),
  useGenerateRecall: () => ({ mutate: state.mutate, isError: state.failed, error: new Error('Generazione non riuscita') }),
}))
vi.mock('@/components/JobProgress', () => ({ JobProgress: ({ onFinished }: { onFinished: (state: string) => void }) => <button onClick={() => onFinished('succeeded')}>Completa il job</button> }))
vi.mock('@/api/jobStatus', () => ({ useJobStatus: () => ({}), jobFinished: () => false }))
function mount(unit = false) {
  render(<QueryClientProvider client={new QueryClient()}><EmptyGeneration lessonId={1} unit={unit ? { id: '1.2', suggestedQtype: 'mirata' } : undefined} onGenerated={vi.fn()} /></QueryClientProvider>)
}
beforeEach(() => { state.suggestions = true; state.failed = false; vi.clearAllMocks() })
it('in modo unità mostra il consiglio, tre domande e nessuna vasta; invia consigliato con count', () => {
  mount(true)
  expect(screen.getByLabelText('Quante')).toHaveValue(3)
  expect(screen.queryByRole('option', { name: 'Vasta' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Quante'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Genera consigliato · Mirata' }))
  expect(state.mutate).toHaveBeenCalledWith({ qtype: 'consigliato', count: 2, unit_ids: ['1.2'] }, expect.anything())
})
it('in modo lezione parte da dieci, include vasta e permette la scelta personalizzata', () => {
  mount()
  expect(screen.getByLabelText('Quante')).toHaveValue(10)
  fireEvent.change(screen.getByLabelText('Tipo di domanda personalizzato'), { target: { value: 'vasta' } })
  fireEvent.click(screen.getByRole('button', { name: 'Genera personalizzato' }))
  expect(state.mutate).toHaveBeenCalledWith({ qtype: 'vasta', count: 10 }, expect.anything())
})
it('senza Jev la riga non compare', () => {
  state.suggestions = false
  mount()
  expect(screen.queryByTestId('recall-empty-generation')).not.toBeInTheDocument()
})
it('un errore della generazione compare in un Alert', () => {
  state.failed = true
  mount()
  expect(screen.getByRole('alert')).toHaveTextContent('Generazione non riuscita')
})

it.each([false, true])('con unità=%s mantiene il job mentre arrivano le nuove domande', async (unit) => {
  const client = new QueryClient()
  const onGenerated = vi.fn()
  state.mutate.mockImplementation((_payload, options) => options.onSuccess({ job_id: 'nuove-domande' }))
  const tree = (available: boolean) => <QueryClientProvider client={client}><EmptyGeneration lessonId={1} unit={unit ? { id: '1.2' } : undefined} available={available} onGenerated={onGenerated} /></QueryClientProvider>
  const view = render(tree(true))
  fireEvent.click(screen.getByRole('button', { name: 'Genera consigliato' }))
  view.rerender(tree(false))
  fireEvent.click(screen.getByRole('button', { name: 'Completa il job' }))
  await vi.waitFor(() => expect(onGenerated).toHaveBeenCalledOnce())
})
