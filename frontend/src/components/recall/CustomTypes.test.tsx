import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { api } from '@/api/client'
import { BASE_RECALL_TYPES, useStudyLesson } from '@/api/recall'
import { ClassifierPanel } from '@/components/lesson/panels/ClassifierPanel'
import { EmptyGeneration } from './EmptyGeneration'
import { QuestionTypeChips } from './QuestionTypeChips'

const custom = { id: 'query-sql', nome: 'Query SQL', icona: 'Database', custom: true, available: true }
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
function mount(available = true, unit = false) {
  const type = { ...custom, available }
  vi.spyOn(api, 'GET').mockImplementation((path => Promise.resolve(ok(
    path.endsWith('/recall/types') ? [...BASE_RECALL_TYPES, type] : path.endsWith('/classifier') ? {
      units: [{ id: '1.1', title: 'Dati', section_id: '1' }], pending: 0,
      jobs: { [`custom:${type.id}`]: { nome: type.nome, icona: type.icona, mode: 'pipeline', state: 'done',
        cells: [{ section_id: '1', value: 'presente', source: 'classifier', state: 'fresh', options: ['presente', 'nessuno'] }] } },
    } : { suggestions: true, units: [{ id: '1.1', suggested_qtype: type.id }] },
  ))) as typeof api.GET)
  const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'sql', state: 'queued' }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ClassifierPanel lessonId={1} /><EmptyGeneration lessonId={1}
      unit={unit ? { id: '1.1', suggestions: true, suggestedQtype: custom.id } : undefined} onGenerated={vi.fn()} /></MemoryRouter>
  </QueryClientProvider>)
  return post
}
afterEach(() => vi.restoreAllMocks())
it('Query SQL dai dati crea riga, icona, consiglio e bottone Genera', async () => {
  const post = mount()
  const row = await screen.findByTestId(`classifier-job-custom:${custom.id}`)
  expect(row).toHaveTextContent(custom.nome)
  expect(row.querySelector('.lucide-database')).toBeInTheDocument()
  const button = await screen.findByRole('button', { name: custom.nome })
  expect(button).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId('question-type-advice')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Genera' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/recall/generate', expect.objectContaining({ body: { qtype: custom.id, count: 10, mock: false } })))
})
it('un tipo senza unità è spento con il tooltip richiesto', async () => {
  mount(false)
  const button = await screen.findByRole('button', { name: custom.nome })
  expect(button).toBeDisabled()
  fireEvent.mouseEnter(button.parentElement!)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Nessuna unità')
  expect(screen.getByRole('button', { name: 'Genera' })).toBeDisabled()
})
it('la scelta manuale di un’unità ignora le etichette', async () => {
  const post = mount(false, true)
  expect(await screen.findByRole('button', { name: custom.nome })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Genera' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/recall/generate', expect.objectContaining({ body: { qtype: custom.id, count: 3, unit_ids: ['1.1'], mock: false } })))
})

it('i controlli nello Studio di una selezione leggono la lezione corrente già osservata', async () => {
  const get = vi.spyOn(api, 'GET').mockImplementation((path => Promise.resolve(ok(
    path.endsWith('/recall/types') ? [...BASE_RECALL_TYPES, custom] : { units: [{ id: '1.1' }] },
  ))) as typeof api.GET)
  function CurrentStudy() {
    const study = useStudyLesson(7)
    return study.data ? <QuestionTypeChips value="quiz" onChange={vi.fn()} unit /> : null
  }
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/studio/selezione/7,8']}><CurrentStudy /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('button', { name: custom.nome })).toBeInTheDocument()
  expect(get).toHaveBeenCalledWith('/api/v1/recall/types', { params: { query: { lesson_id: 7, materia: undefined } } })
})

it('un tipo con un nome lungo si tronca dentro il pannello e mostra il nome intero al passaggio', () => {
  const nome = 'Domande di farmacologia clinica sulle interazioni tra farmaci antiaritmici'
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <QuestionTypeChips value="quiz" onChange={vi.fn()} types={[...BASE_RECALL_TYPES, { ...custom, nome }]} />
  </MemoryRouter></QueryClientProvider>)
  const chip = screen.getByRole('button', { name: nome })
  expect(chip).toHaveAttribute('title', nome)
  expect(chip).toHaveClass('max-w-full')
  expect(chip.querySelector('.truncate')).toHaveTextContent(nome)
})
