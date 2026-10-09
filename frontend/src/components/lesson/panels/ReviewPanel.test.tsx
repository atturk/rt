import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { ApiError } from '@/api/client'
import { MemoryRouter } from 'react-router'
import type { Schemas } from '@/api/client'
import { AudioProvider } from '../audio'
import { ReviewPanel } from './ReviewPanel'

const state = vi.hoisted(() => ({ phone: false, units: [] as Schemas['ReviewUnit'][], items: [] as Schemas['IssueItem'][], jobs: [] as Schemas['Job'][], decide: vi.fn(), undo: vi.fn(), run: vi.fn(), cancel: vi.fn() }))
vi.mock('@/api/hooks', () => ({
  useReviewUnits: () => ({ data: state.units }),
  useIssues: () => ({ data: { items: state.items } }), useDecisions: () => ({ data: state.items.flatMap((i) => i.decision ? [i.decision] : []) }),
  useDecideIssue: () => ({ mutateAsync: state.decide }), useUndoDecision: () => ({ mutateAsync: state.undo }), useRunJob: () => ({ mutateAsync: state.run }),
}))
vi.mock('@/lib/preferences', () => ({ usePreference: (_name: string, fallback: unknown) => useState(fallback) }))
vi.mock('@/api/relevance', () => ({ useRelevance: () => ({ data: { mode: 'active', summary: { missing: 0, stale: 0, errors: 0 }, units: [{ unit_id: '1.1', title: 'Acidosi', review_included: true, prediction: 'didactic', stale: false }] } }) }))
vi.mock('@/api/jobs', () => ({ useJobs: () => ({ data: state.jobs }), useCancelJob: () => ({ mutate: state.cancel }) }))
vi.mock('@/lib/phone', () => ({ useIsPhone: () => state.phone }))
const issue: Schemas['IssueItem'] = { needs_reconfirmation: false, issue: { id: 'a', type: 'ERR_CONCETTUALE', severity: 'high', unit_id: '1.1', claim: 'Il pH è 6.', suggested_fix: 'Il pH è 7.', reason: 'Valore errato' }, context: { timecode: '00:00', start_s: 0, unit_content: 'Il pH è 6.' } }
function mount(phases: Record<string, string> = { rewrite: 'VALID', review: 'VALID' }, beforeAction?: () => Promise<void>, markdown?: string, detail: Partial<Schemas['LessonDetail']> = {}) {
  return render(<MemoryRouter><AudioProvider><ReviewPanel lesson={{ id: 1, phases, has_audio: false, folder_name: 'acidosi', path: '/acidosi', data: '', ora: '', materia: '', titolo: '', argomenti: '', docente: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, phase_report: [], segment_count: 0, outline_approved: false, ...detail }} beforeAction={beforeAction} markdown={markdown} /></AudioProvider></MemoryRouter>)
}
beforeEach(() => { vi.clearAllMocks(); state.items = [issue]; state.units = []; state.jobs = []; state.phone = false })
it('salva le modifiche prima della decisione, senza scorciatoie', async () => {
  let resolve!: () => void
  const save = vi.fn(() => new Promise<void>((r) => { resolve = r }))
  mount(undefined, save)
  fireEvent.keyDown(window, { key: 'a' })
  expect(state.decide).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  expect(save).toHaveBeenCalledOnce()
  expect(state.decide).not.toHaveBeenCalled()
  resolve()
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
})
it('non decide quando il salvataggio fallisce', async () => {
  mount(undefined, async () => { throw new Error('Bozza non valida') })
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
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
  expect(screen.getByRole('button', { name: 'Ricostruisci il documento' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Decise 1' }))
  expect(screen.getByRole('list', { name: 'Decise' })).toHaveTextContent('Il pH è 6.')
})
it('modifica una correzione e permette di annullare l’ultima decisione', async () => {
  mount()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByLabelText('Correzione proposta'), { target: { value: 'Il pH è 7,35.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Applica la tua correzione' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,35.' }))
})
it('passaggio cambiato: chiude l\'issue, ma le decisioni restano possibili', async () => {
  mount(undefined, undefined, '## 1. Sezione\n### 1.1 Unità\n00:00\nIl pH è 7.')
  expect(screen.getByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toBeEnabled()
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

it.each([
  ['MISSING', 'Mai verificata', 'Verifica tutta la lezione', { type: 'run_phase', phase: 'review' }],
  ['PARTIAL', 'Verificate 2 unità su 5', 'Verifica le unità mancanti (3)', { type: 'run_phase', phase: 'review' }],
  ['STALE', 'Il testo è cambiato dopo la verifica', 'Aggiorna il documento', { type: 'run_pipeline', with_review: true }],
  ['VALID', 'Tutte decise', 'Ricostruisci il documento', { type: 'run_phase', phase: 'build' }],
])('stato %s: titolo, azione e payload', async (review, title, button, payload) => {
  state.items = []
  mount({ rewrite: 'VALID', review, build: 'STALE' }, undefined, undefined, { review_progress: { reviewed: 2, total: 5 } })
  expect(screen.getByRole('status')).toHaveTextContent(title)
  expect(screen.queryByRole('button', { name: 'Riprendi la pipeline' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: button }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith(payload))
})
it('review completa con issue da decidere: conteggio e documento ricostruibile', () => {
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('1 da decidere su 1')
  expect(screen.getByRole('button', { name: 'Ricostruisci il documento' })).toBeEnabled()
})
it('verifica parziale: unità mancanti dal registro e documento ricostruibile con conferma', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never'), unit('2.2', 'excluded')]
  mount({ rewrite: 'VALID', review: 'PARTIAL', build: 'STALE' }, undefined, undefined, {
    phase_report: [{ phase: 'build', status: 'STALE', reason: '', warnings: [{ code: 'review_partial', message: 'Revisione incompleta', count: null }] }],
  })
  fireEvent.click(screen.getByRole('button', { name: 'Ricostruisci il documento' }))
  expect(screen.getByTestId('build-confirm-warnings')).toHaveTextContent('Revisione incompleta')
  fireEvent.click(screen.getByRole('button', { name: 'Crea il documento comunque' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'build' }))
  fireEvent.click(screen.getByRole('button', { name: 'Verifica le unità mancanti (2)' }))
  await waitFor(() => expect(state.run).toHaveBeenLastCalledWith({ type: 'run_phase', phase: 'review', units: ['1.2', '2.1'] }))
})
it('build già valido disattiva il pulsante e mostra Documento aggiornato', () => {
  state.items = []
  mount({ rewrite: 'VALID', review: 'VALID', build: 'VALID' })
  expect(screen.getByRole('button', { name: 'Documento aggiornato' })).toBeDisabled()
})
it('la ricostruzione richiede la conferma quando ci sono avvisi', async () => {
  state.items = []
  mount({ rewrite: 'VALID', review: 'VALID', build: 'STALE' }, undefined, undefined, {
    phase_report: [{ phase: 'build', status: 'STALE', reason: '', warnings: [{ code: 'pending', message: 'Avviso di prova', count: 1 }] }],
  })
  fireEvent.click(screen.getByRole('button', { name: 'Ricostruisci il documento' }))
  expect(state.run).not.toHaveBeenCalled()
  expect(screen.getByTestId('build-confirm-warnings')).toHaveTextContent('Avviso di prova')
  fireEvent.click(screen.getByRole('button', { name: 'Crea il documento comunque' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'build' }))
})

it('testo cambiato: conserva le correzioni per default e permette di rifare la verifica in fondo', async () => {
  mount({ rewrite: 'VALID', review: 'STALE', build: 'STALE' })
  expect(screen.getByText('Le correzioni fatte a mano non rifanno la verifica.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Ricostruisci il documento' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica di nuovo tutta la lezione' }))
  expect(state.run).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica tutte le unità' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', force: true }))
})

it.each([false, true])('modifica col doppio clic o un tocco sul telefono=%s', phone => {
  state.phone = phone
  mount()
  const box = screen.getByTestId('proposed-correction')
  if (phone) fireEvent.click(box); else fireEvent.doubleClick(box)
  expect(screen.getByRole('textbox', { name: 'Correzione proposta' })).toHaveValue('Il pH è 7.')
  expect(screen.getByRole('button', { name: 'Ripristina la correzione proposta' })).toBeDisabled()
})
it('clic fuori applica il testo cambiato, senza cambi non decide', async () => {
  mount()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.mouseDown(document.body)
  expect(state.decide).not.toHaveBeenCalled()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Il pH è 7,4.' } })
  fireEvent.mouseDown(document.body)
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,4.' }))
})
it('Esc annulla e il ripristino recupera la proposta senza decidere', () => {
  mount()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Altro testo' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ripristina la correzione proposta' }))
  expect(screen.getByRole('textbox')).toHaveValue('Il pH è 7.')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Altro testo' } })
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' })
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.getByTestId('proposed-correction')).toHaveTextContent('Il pH è 7.')
  expect(state.decide).not.toHaveBeenCalled()
})
it('Mantieni durante la modifica scarta il testo e manda rejected; pulsanti con sole icone', async () => {
  mount()
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toHaveTextContent('')
  const keep = screen.getByRole('button', { name: 'Mantieni il testo attuale' })
  expect(keep).toHaveTextContent('')
  expect(keep.querySelector('svg')).toBeInTheDocument()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Altro testo' } })
  fireEvent.click(keep)
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'rejected', text: undefined }))
})
it('il testo vuoto non si applica; Ctrl+Invio applica il testo scritto', async () => {
  mount()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: ' ' } })
  fireEvent.mouseDown(document.body)
  expect(state.decide).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Applica la tua correzione' })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Il pH è 7,4.' } })
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', ctrlKey: true })
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,4.' }))
})

it('in fondo a Verifica mostra le tacche, senza il vecchio footer di testo', () => {
  mount()
  expect(screen.getByTestId('unit-strip-revisore')).toHaveTextContent('1/1')
  expect(screen.queryByText(/^Unità per il recaller:/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Rivedi le etichette · classificatore aggiornato' }))
})

it('il suggerimento non letterale si modifica dal claim e non si accetta a vuoto', async () => {
  state.items = [{ ...issue, fix_text: null, issue: { ...issue.issue, suggested_fix: 'Precisare che il valore normale è 7,4.' } }]
  mount()
  expect(screen.getByText('Suggerimento')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accetta la correzione' })).not.toBeInTheDocument()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  expect(screen.getByRole('textbox', { name: 'Testo corretto' })).toHaveValue('Il pH è 6.')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Il pH è 7,4.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Applica la tua correzione' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,4.' }))
})

const unit = (unit_id: string, state: Schemas['ReviewUnit']['state'], issues_total = 0): Schemas['ReviewUnit'] => ({ unit_id, title: `Titolo ${unit_id}`, state, reviewed_at: '2026-10-09T11:07:00', model: 'modello-test', issues_total, issues_pending: issues_total })
it('mostra il riassunto e tutti i sei stati delle unità', () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'issues', 2), unit('2.1', 'changed'), unit('2.2', 'never'), unit('3.1', 'excluded'), unit('3.2', 'failed')]
  mount()
  expect(screen.getByText('2 unità verificate su 6 · 1 senza problemi')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 6' }))
  for (const status of ['ok', 'issues', 'changed', 'never', 'excluded', 'failed']) expect(screen.getByTestId(`review-unit-${status}`)).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /^Verifica l'unità/ })).toHaveLength(3)
})
it('raggruppa per unità: cronologico e poi gravità', () => {
  state.units = [unit('1.1', 'issues', 1), unit('1.2', 'issues', 1)]
  state.items = [{ ...issue, issue: { ...issue.issue, severity: 'low' } }, { ...issue, issue: { ...issue.issue, id: 'b', unit_id: '1.2' } }]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Per unità' }))
  expect(screen.getAllByTestId('review-issue-group').map(el => el.getAttribute('data-unit'))).toEqual(['1.1', '1.2'])
  fireEvent.change(screen.getByRole('combobox', { name: 'Ordine delle issue' }), { target: { value: 'gravita' } })
  expect(screen.getAllByTestId('review-issue-group').map(el => el.getAttribute('data-unit'))).toEqual(['1.2', '1.1'])
})
it('la ri-verifica di una unità chiede conferma e forza solo quella', async () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 1' }))
  fireEvent.click(screen.getByRole('button', { name: 'Azioni sull’unità 1.1' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Verifica di nuovo' }))
  expect(state.run).not.toHaveBeenCalled()
  expect(screen.getByText('Le decisioni prese restano agganciate alle issue ritrovate')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica di nuovo' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true }))
})
it('tutto verificato: niente unità mancanti, la ri-verifica globale chiede conferma', () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  expect(screen.queryByRole('button', { name: /^Verifica le unità mancanti/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica di nuovo tutta la lezione' }))
  expect(screen.getByText('Rifà la verifica di tutte le unità, anche di quelle già verificate.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(state.run).not.toHaveBeenCalled()
})
it('il conto delle issue apre Da decidere con filtro togliibile', () => {
  state.units = [unit('1.1', 'issues', 1)]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 1' }))
  fireEvent.click(screen.getByRole('button', { name: '1 issue nell’unità 1.1' }))
  expect(screen.getByTestId('review-unit-filter')).toHaveTextContent('Unità 1.1')
  fireEvent.click(screen.getByRole('button', { name: 'Togli il filtro per unità' }))
  expect(screen.queryByTestId('review-unit-filter')).not.toBeInTheDocument()
})
it('claim_changed mostra l’errore nella card e passa a Testo cambiato', async () => {
  state.decide.mockRejectedValueOnce(new ApiError(409, 'claim_changed', 'Il testo è già cambiato: modificalo a mano o chiudi l’issue'))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  expect(await screen.findByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Il testo è già cambiato')
})

it('verifica solo le unità cambiate o mai verificate', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica le unità mancanti (2)' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', units: ['1.2', '2.1'] }))
})
it('verifica solo le unità selezionate', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never'), unit('2.2', 'never')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 4' }))
  expect(screen.getByRole('checkbox', { name: "Seleziona l'unità 1.1" })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: "Seleziona l'unità 1.2" }))
  fireEvent.click(screen.getByRole('checkbox', { name: "Seleziona l'unità 2.2" }))
  fireEvent.click(screen.getByRole('button', { name: 'Verifica le selezionate (2)' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', units: ['1.2', '2.2'] }))
  expect(screen.queryByRole('button', { name: /^Verifica le selezionate/ })).not.toBeInTheDocument()
})
it.each(['review_unit', 'run_phase'])('il job singolo %s mostra Verifico solo nella sua riga; la riga porta al testo', type => {
  state.units = [unit('1.1', 'never'), unit('1.2', 'ok')]
  state.jobs = [{ id: 'j', type, state: 'running', payload: { phase: 'review', unit: '1.1' }, attempts: 0, cancel_requested: false } as Schemas['Job']]
  const scroll = vi.fn()
  window.addEventListener('rt-editor-scroll', scroll)
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 2' }))
  expect(screen.getAllByText('Verifico…')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: /Titolo 1.1/ }))
  expect(scroll).toHaveBeenCalled()
  window.removeEventListener('rt-editor-scroll', scroll)
})
it('gli errori dei suggerimenti restano nella card', async () => {
  state.decide.mockRejectedValueOnce(new ApiError(409, 'suggestion_only', 'È un suggerimento, non una correzione: scrivi tu il testo'))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('È un suggerimento')
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('È un suggerimento')
})

it('la riga mostra Verifico già mentre si accoda il job', async () => {
  state.units = [unit('1.1', 'never')]
  let finish!: () => void
  state.run.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Unità 1' }))
  fireEvent.click(screen.getByRole('button', { name: "Verifica l'unità 1.1" }))
  try { await waitFor(() => expect(screen.getByText('Verifico…')).toBeInTheDocument()) }
  finally { finish() }
})
