import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/api/client'
import { waitFor } from '@testing-library/react'
import type { Schemas } from '@/api/client'
import { MemoryRouter, Route, Routes } from 'react-router'
import { LessonPage } from './lessons'

const workflow = vi.hoisted(() => ({ outline: undefined as Schemas['Outline'] | undefined, document: undefined as Schemas['LessonDocument'] | undefined, jobs: [] as Schemas['Job'][], ready: false }))

vi.mock('@/api/hooks', () => ({
  useLesson: () => ({ data: { id: 1, titolo: 'Acidosi', materia: 'FISIOLOGIA', data: '2026-10-02', docente: 'Rossi', unit_count: 9, duration_seconds: 4800, phases: { rewrite: workflow.ready ? 'VALID' : 'MISSING' }, has_audio: false, actions: { recall: { available: false, preview: false }, images: { available: false, preview: false }, export_markdown: { available: true, preview: false }, export_zip: { available: true, preview: false } } } }),
  useLessonDocument: () => ({ data: workflow.document }),
}))
vi.mock('@/api/jobs', () => ({ useJobs: () => ({ data: workflow.jobs }), useOutline: () => ({ data: workflow.outline }), useJob: () => ({ data: undefined }), useApproveOutline: () => ({}), useReviseOutline: () => ({}), useSuspendOutline: () => ({}) }))
vi.mock('@/components/jobs/JobsIndicator', () => ({ LessonWaiting: () => null }))
vi.mock('@/components/jobs/PhaseProgress', () => ({ PhaseProgress: () => null }))
vi.mock('@/components/lesson/panels/QuestionsPanel', () => ({ QuestionsPanel: () => null }))
vi.mock('@/components/lesson/panels/EnrichmentPanel', () => ({ EnrichmentPanel: () => null }))
vi.mock('@/components/lesson/panels/ClassifierPanel', () => ({ ClassifierPanel: () => null }))
vi.mock('@/components/lesson/LessonEditor', () => ({ LessonEditor: ({ document, locked, unitTasks }: { document: Schemas['LessonDocument']; locked: boolean; unitTasks?: Record<string, string> }) => <><textarea aria-label="Editor" value={document.markdown} readOnly={locked} onChange={() => undefined} /><output aria-label="Stati unità">{JSON.stringify(unitTasks)}</output></> }))

beforeEach(() => { localStorage.clear(); workflow.outline = undefined; workflow.document = undefined; workflow.jobs = []; workflow.ready = false })
afterEach(() => vi.restoreAllMocks())

it('la preferenza sul server controlla lo stato di studio nel link ZIP', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(['preferences'], { 'export.study': true })
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: false, error: undefined, response: new Response('{}') } as never)
  vi.spyOn(api, 'GET').mockResolvedValue({ data: { 'export.study': false }, error: undefined, response: new Response('{}') } as never)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/lezioni/1']}><Routes><Route path="/lezioni/:lessonId" element={<LessonPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Esporta' }))
  const zip = screen.getByRole('menuitem', { name: 'Tutti i dati (zip)' })
  expect(zip).toHaveAttribute('href', '/api/v1/lessons/1/export?format=zip&scope=all&study=1')
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Includi lo stato di studio' }))
  await waitFor(() => expect(zip).toHaveAttribute('href', '/api/v1/lessons/1/export?format=zip&scope=all'))
  expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'export.study' } }, body: false })
  expect(screen.getByRole('menuitem', { name: 'Markdown' })).toHaveAttribute('href', '/api/v1/lessons/1/export?format=markdown')
})

it('mostra i metadati sotto il titolo e le azioni del wireframe Main', () => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/lezioni/1']}><Routes><Route path="/lezioni/:lessonId" element={<LessonPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Acidosi')
  expect(screen.getByTestId('lesson-path')).toHaveTextContent('Fisiologia · 2 ott · Rossi')
  expect(screen.getByTestId('lesson-meta')).toHaveTextContent('9 unità · 1 h 20 min')
  expect(document.querySelector('header')).not.toHaveTextContent('Fisiologia')
  const actions = within(screen.getByTestId('lesson-actions'))
  expect(actions.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Domande', 'Studio', 'Arricchimento', 'Verifica con LLM', 'Dettagli', 'Esporta'])
  fireEvent.click(actions.getByRole('button', { name: 'Domande' }))
  expect(screen.getByRole('complementary', { name: 'Domande' })).toBeInTheDocument()
  fireEvent.click(actions.getByRole('button', { name: 'Arricchimento' }))
  expect(screen.getAllByRole('complementary')).toHaveLength(1)
  expect(screen.getByRole('complementary', { name: 'Arricchimento' })).toBeInTheDocument()
})

it('passa dalla scaletta ai checkpoint nell’editor, poi al testo completo bloccato fino alla fine dei job', async () => {
  workflow.outline = { lesson_title: 'Acidosi', approved: false, timer_suspended: true, macro_sections: [{ id: '1', title: 'Sezione', units: ['1.1', '1.2'].map((id) => ({ id, title: `Unità ${id}`, key_concepts: [], start_segment_id: 's1', end_segment_id: 's2' })) }] }
  workflow.jobs = [{ id: 'j', type: 'run_pipeline', payload: {}, state: 'waiting_for_decision', decision: { kind: 'outline_approval' }, attempts: 1, cancel_requested: false }]
  const client = new QueryClient()
  const component = () => <QueryClientProvider client={client}><MemoryRouter initialEntries={['/lezioni/1']}><Routes><Route path="/lezioni/:lessonId" element={<LessonPage />} /></Routes></MemoryRouter></QueryClientProvider>
  const view = render(component())
  expect(screen.getByTestId('outline-approval')).toBeInTheDocument()
  expect(screen.queryByLabelText('Editor')).toBeNull()
  workflow.outline = { ...workflow.outline, approved: true }
  workflow.jobs = [{ ...workflow.jobs[0], state: 'running', progress: { phase: 'rewrite', unit_id: '1.2' } }]
  workflow.document = { markdown: '## 1. Sezione\n### 1.1 Unità\n00:00\nTesto dal checkpoint.', html: '', final: false, pending: false, sections: [{ unit_id: '1.1', title: 'Unità', start_segment_id: 's1', end_segment_id: 's2' }] }
  view.rerender(component())
  expect((await screen.findByLabelText<HTMLTextAreaElement>('Editor')).value).toContain('Testo dal checkpoint.')
  expect(screen.getByLabelText('Stati unità')).toHaveTextContent('"1.1":"done","1.2":"working"')
  workflow.ready = true
  workflow.document = { ...workflow.document, markdown: 'Documento completo' }
  workflow.jobs = [{ ...workflow.jobs[0], type: 'unit_relevance', progress: { phase: 'unit_relevance' } }]
  view.rerender(component())
  expect(screen.getByLabelText('Editor')).toHaveValue('Documento completo')
  expect(screen.getByLabelText('Editor')).toHaveAttribute('readonly')
  expect(screen.getByLabelText('Stati unità')).toBeEmptyDOMElement()
  workflow.jobs = []
  view.rerender(component())
  expect(screen.getByLabelText('Editor')).not.toHaveAttribute('readonly')
})

it('una lezione già rielaborata resta leggibile anche senza approvazione della scaletta persistita', async () => {
  workflow.ready = true
  workflow.outline = { lesson_title: 'Acidosi', approved: false, timer_suspended: false, macro_sections: [] }
  workflow.document = { markdown: 'Lezione importata', html: '', sections: [], final: true, pending: false }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/lezioni/1']}><Routes><Route path="/lezioni/:lessonId" element={<LessonPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByLabelText('Editor')).toHaveValue('Lezione importata')
  expect(screen.queryByTestId('outline-approval')).toBeNull()
})
