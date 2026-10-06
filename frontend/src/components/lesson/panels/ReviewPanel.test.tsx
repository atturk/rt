import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import type { Schemas } from '@/api/client'
import { AudioProvider } from '../audio'
import { ReviewPanel } from './ReviewPanel'

const state = vi.hoisted(() => ({ phone: false, items: [] as Schemas['IssueItem'][], jobs: [] as Schemas['Job'][], decide: vi.fn(), undo: vi.fn(), run: vi.fn(), cancel: vi.fn() }))
vi.mock('@/api/hooks', () => ({
  useIssues: () => ({ data: { items: state.items } }), useDecisions: () => ({ data: state.items.flatMap((i) => i.decision ? [i.decision] : []) }),
  useDecideIssue: () => ({ mutateAsync: state.decide }), useUndoDecision: () => ({ mutateAsync: state.undo }), useRunJob: () => ({ mutateAsync: state.run }),
}))
vi.mock('@/api/jobs', () => ({ useJobs: () => ({ data: state.jobs }), useCancelJob: () => ({ mutate: state.cancel }) }))
vi.mock('@/lib/phone', () => ({ useIsPhone: () => state.phone }))
const issue: Schemas['IssueItem'] = { issue: { id: 'a', type: 'ERR_CONCETTUALE', severity: 'high', unit_id: '1.1', claim: 'Il pH è 6.', suggested_fix: 'Il pH è 7.', reason: 'Valore errato' }, context: { timecode: '00:00', start_s: 0, unit_content: 'Il pH è 6.' } }
function mount(phases = { rewrite: 'VALID', review: 'VALID' }, beforeAction?: () => Promise<void>, markdown?: string) {
  return render(<MemoryRouter><AudioProvider><ReviewPanel lesson={{ id: 1, phases, has_audio: false, folder_name: 'acidosi', path: '/acidosi', data: '', ora: '', materia: '', titolo: '', argomenti: '', docente: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, phase_report: [], segment_count: 0, outline_approved: false }} beforeAction={beforeAction} markdown={markdown} /></AudioProvider></MemoryRouter>)
}
beforeEach(() => { vi.clearAllMocks(); state.items = [issue]; state.jobs = []; state.phone = false })
it('salva le modifiche prima della decisione, senza scorciatoie', async () => {
  let resolve!: () => void
  const save = vi.fn(() => new Promise<void>((r) => { resolve = r }))
  mount(undefined, save)
  fireEvent.keyDown(window, { key: 'a' })
  expect(state.decide).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta' }))
  expect(save).toHaveBeenCalledOnce()
  expect(state.decide).not.toHaveBeenCalled()
  resolve()
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
})
it('non decide quando il salvataggio fallisce', async () => {
  mount(undefined, async () => { throw new Error('Bozza non valida') })
  fireEvent.click(screen.getByRole('button', { name: 'Accetta' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Bozza non valida')
  expect(state.decide).not.toHaveBeenCalled()
})
it('mostra mai verificata, in corso e tutte decise', () => {
  state.items = []
  const view = mount({ rewrite: 'VALID', review: 'MISSING' })
  expect(screen.getByRole('status')).toHaveTextContent('Mai verificata')
  view.unmount()
  state.jobs = [{ id: 'j', state: 'running', type: 'run_phase', payload: { phase: 'review' }, attempts: 0, cancel_requested: false } as Schemas['Job']]
  const running = mount()
  expect(screen.getByRole('status')).toHaveTextContent('In corso')
  fireEvent.click(screen.getByRole('button', { name: 'Interrompi' }))
  expect(state.cancel).toHaveBeenCalledWith('j')
  running.unmount()
  state.jobs = []
  state.items = [{ ...issue, decision: { issue_id: 'a', decision: 'accepted', resolved_by: 'user', timestamp: '2026-10-03' } }]
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('Tutte decise')
  expect(screen.getByRole('button', { name: 'Riprendi la pipeline' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Decise 1' }))
  expect(screen.getByRole('list', { name: 'Decise' })).toHaveTextContent('Il pH è 6.')
})
it('modifica una correzione e permette di annullare l’ultima decisione', async () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Modifica' }))
  fireEvent.change(screen.getByLabelText('Testo corretto'), { target: { value: 'Il pH è 7,35.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Salva modifica' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,35.' }))
})
it('passaggio cambiato: chiude l\'issue, ma le decisioni restano possibili', async () => {
  mount(undefined, undefined, '## 1. Sezione\n### 1.1 Unità\n00:00\nIl pH è 7.')
  expect(screen.getByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Accetta' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: "Chiudi l'issue" }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'rejected', text: undefined }))
})

it('sul telefono mostra testo e correzione, con elenco a richiesta', () => {
  state.phone = true
  mount()
  expect(screen.getByText('Nel testo')).toBeInTheDocument()
  expect(screen.getByText('Correzione proposta')).toBeInTheDocument()
  expect(screen.queryByRole('list')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Elenco (1)' }))
  expect(screen.getByRole('list', { name: 'Da decidere' })).toBeInTheDocument()
})
