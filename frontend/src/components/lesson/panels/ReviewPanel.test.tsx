import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { ApiError } from '@/api/client'
import { MemoryRouter } from 'react-router'
import type { Schemas } from '@/api/client'
import { AudioProvider } from '../audio'
import { ReviewPanel } from './ReviewPanel'

const state = vi.hoisted(() => ({ phone: false, units: [] as Schemas['ReviewUnit'][], items: [] as Schemas['IssueItem'][], jobs: [] as Schemas['Job'][], decide: vi.fn(), undo: vi.fn(), run: vi.fn(), cancel: vi.fn(), refetch: vi.fn() }))
vi.mock('@/api/hooks', () => ({
  useReviewUnits: () => ({ data: state.units }),
  useIssues: () => ({ data: { items: state.items }, refetch: state.refetch }), useDecisions: () => ({ data: state.items.flatMap((i) => i.decision ? [i.decision] : []) }),
  useDecideIssue: () => ({ mutateAsync: state.decide }), useUndoDecision: () => ({ mutateAsync: state.undo }), useRunJob: () => ({ mutateAsync: state.run }),
}))
vi.mock('@/lib/preferences', () => ({ usePreference: (_name: string, fallback: unknown) => useState(fallback) }))
vi.mock('@/api/relevance', () => ({ useRelevance: () => ({ data: { mode: 'active', summary: { missing: 0, stale: 0, errors: 0 }, units: [{ unit_id: '1.1', title: 'Acidosi', review_included: true, prediction: 'didactic', stale: false }] } }) }))
vi.mock('@/api/jobs', () => ({ useJobs: () => ({ data: state.jobs }), useCancelJob: () => ({ mutate: state.cancel }) }))
vi.mock('@/lib/phone', () => ({ useIsPhone: () => state.phone }))
const issue: Schemas['IssueItem'] = { quote_status: 'found', needs_reconfirmation: false, issue: { id: 'a', type: 'ERR_CONCETTUALE', severity: 'high', unit_id: '1.1', claim: 'Il pH è 6.', suggested_fix: 'Il pH è 7.', reason: 'Valore errato' }, context: { timecode: '00:00', start_s: 0, unit_content: 'Il pH è 6.' } }
function mount(phases: Record<string, string> = { rewrite: 'VALID', review: 'VALID' }, beforeAction?: () => Promise<void>, _markdown?: string, detail: Partial<Schemas['LessonDetail']> = {}, initialEntry = '/') {
  return render(<MemoryRouter initialEntries={[initialEntry]}><AudioProvider><ReviewPanel lesson={{ id: 1, phases, review_progress: { reviewed: 0, total: 0, completed_once: phases.review === 'VALID' }, has_audio: false, folder_name: 'acidosi', path: '/acidosi', data: '', ora: '', materia: '', titolo: '', argomenti: '', docente: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, media_count: 0, phase_report: [], segment_count: 0, outline_approved: false, ...detail }} beforeAction={beforeAction} /></AudioProvider></MemoryRouter>)
}
beforeEach(() => { vi.clearAllMocks(); state.items = [issue]; state.units = []; state.jobs = []; state.phone = false; state.refetch.mockImplementation(() => Promise.resolve({ data: { items: state.items } })) })
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
  expect(screen.queryByRole('button', { name: 'Ricostruisci il documento' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  expect(screen.getByRole('list', { name: 'Issue dell’unità 1.1' })).toHaveTextContent('Il pH è 7.')
})
it('modifica una correzione e permette di annullare l’ultima decisione', async () => {
  mount()
  fireEvent.doubleClick(screen.getByTestId('proposed-correction'))
  fireEvent.change(screen.getByLabelText('Correzione proposta'), { target: { value: 'Il pH è 7,35.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Applica la tua correzione' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,35.' }))
})
it('passaggio cambiato: mantiene il testo e chiude l\'issue', async () => {
  state.items = [{ ...issue, quote_status: 'changed' }]
  mount()
  expect(within(screen.getByTestId('issue-detail')).getByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accetta la correzione' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'rejected', text: undefined }))
})

it('sul telefono mostra testo, correzione ed elenco sempre visibile', () => {
  state.phone = true
  mount()
  expect(screen.getByText('Nel testo')).toBeInTheDocument()
  expect(screen.getByText('Correzione proposta')).toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Unità della verifica' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Elenco/ })).not.toBeInTheDocument()
})

it.each([
  ['MISSING', 'Mai verificata', ['never', 'never', 'never'], ['1.1', '1.2', '1.3']],
  ['PARTIAL', '2 unità da verificare', ['ok', 'changed', 'never'], ['1.2', '1.3']],
  ['STALE', '2 unità da verificare', ['ok', 'changed', 'failed'], ['1.2', '1.3']],
])('stato %s: titolo, azione e payload dalle sole unità da fare', async (review, title, states, ids) => {
  state.items = []
  state.units = states.map((status, i) => unit(`1.${i + 1}`, status as Schemas['ReviewUnit']['state']))
  mount({ rewrite: 'VALID', review, build: 'STALE' })
  expect(screen.getByRole('status')).toHaveTextContent(title)
  expect(screen.queryByRole('button', { name: 'Riprendi la pipeline' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', units: ids }))
})
it('review completa con issue da decidere: conteggio e documento automatico', () => {
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('1 da decidere')
  expect(screen.queryByRole('button', { name: 'Ricostruisci il documento' })).not.toBeInTheDocument()
})
it('verifica parziale: unità mancanti dal registro e documento automatico senza conferma', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never'), unit('2.2', 'excluded')]
  mount({ rewrite: 'VALID', review: 'PARTIAL', build: 'STALE' }, undefined, undefined, {
    phase_report: [{ phase: 'build', status: 'STALE', reason: '', warnings: [{ code: 'review_partial', message: 'Revisione incompleta', count: null }] }],
  })
  expect(screen.queryByTestId('build-confirm-warnings')).not.toBeInTheDocument()
  expect(state.run).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica' }))
  await waitFor(() => expect(state.run).toHaveBeenLastCalledWith({ type: 'run_phase', phase: 'review', units: ['1.2', '2.1'] }))
})
it('build già valido e mostra Documento aggiornato', () => {
  state.items = []
  mount({ rewrite: 'VALID', review: 'VALID', build: 'VALID' })
  expect(screen.getByTestId('documents-status')).toHaveTextContent('Documento aggiornato')
})
it('gli avvisi non richiedono conferma per i documenti automatici', async () => {
  state.items = []
  mount({ rewrite: 'VALID', review: 'VALID', build: 'STALE' }, undefined, undefined, {
    phase_report: [{ phase: 'build', status: 'STALE', reason: '', warnings: [{ code: 'pending', message: 'Avviso di prova', count: 1 }] }],
  })
  expect(screen.getByTestId('documents-status')).toHaveTextContent('Documento in aggiornamento')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(state.run).not.toHaveBeenCalled()
})

it('testo cambiato: verifica globale immediata dal menu dopo una verifica completa', async () => {
  mount({ rewrite: 'VALID', review: 'STALE', build: 'STALE' }, undefined, undefined, { review_progress: { reviewed: 0, total: 1, completed_once: true } })
  expect(screen.queryByRole('button', { name: 'Ricostruisci il documento' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui tutta la lezione' }))
  expect(screen.queryByRole('group', { name: /Riesegui/ })).not.toBeInTheDocument()
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', force: true }))
})

it.each([false, true])('modifica col doppio clic o un tocco sul telefono=%s', phone => {
  state.phone = phone
  mount()
  const box = screen.getByTestId('proposed-correction')
  if (phone) fireEvent.click(box); else fireEvent.doubleClick(box)
  expect(screen.getByRole('textbox', { name: 'Correzione proposta' })).toHaveValue('Il pH è 7.')
  expect(screen.getByRole('button', { name: 'Ripristina la correzione proposta' })).toHaveAttribute('aria-disabled', 'true')
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
  expect(screen.getByRole('button', { name: 'Applica la tua correzione' })).toHaveAttribute('aria-disabled', 'true')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Il pH è 7,4.' } })
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', ctrlKey: true })
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'edited', text: 'Il pH è 7,4.' }))
})

it('le unità escluse aprono il Classificatore, senza striscia nel pannello', () => {
  state.units = [unit('1.1', 'excluded')]
  mount()
  expect(screen.queryByTestId('unit-strip-revisore')).not.toBeInTheDocument()
  expect(screen.getByText('Esclusa dal classificatore')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Apri il Classificatore' }))
})

it('il suggerimento non letterale si modifica dal claim e non si accetta a vuoto', async () => {
  state.items = [{ ...issue, fix_text: null, issue: { ...issue.issue, suggested_fix: 'Precisare che il valore normale è 7,4.' } }]
  mount()
  expect(screen.queryByText('Suggerimento')).not.toBeInTheDocument()
  expect(screen.getByText('Correzione proposta')).toBeInTheDocument()
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
  expect(screen.getByRole('status')).toHaveTextContent('2/5 unità verificate')
  for (const status of ['ok', 'issues', 'changed', 'never', 'excluded', 'failed']) expect(screen.getByTestId(`review-unit-${status}`)).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /^Verifica l'unità/ }).filter(button => button.getAttribute('aria-disabled') !== 'true')).toHaveLength(3)
})
it('raggruppa per unità: cronologico e poi gravità', () => {
  state.units = [unit('1.1', 'issues', 1), unit('1.2', 'issues', 1)]
  state.items = [{ ...issue, issue: { ...issue.issue, severity: 'low' } }, { ...issue, issue: { ...issue.issue, id: 'b', unit_id: '1.2' } }]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Apri le issue dell’unità 1.2' }))
  expect(screen.getAllByTestId('review-issue-group').map(el => el.closest('[data-unit]')?.getAttribute('data-unit'))).toEqual(['1.1', '1.2'])
  fireEvent.click(screen.getByRole('button', { name: 'Ordine delle issue' }))
  expect(screen.getAllByTestId('review-issue-group').map(el => el.closest('[data-unit]')?.getAttribute('data-unit'))).toEqual(['1.2', '1.1'])
})
it('la ri-verifica di una unità parte subito e forza solo quella', async () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni sull’unità 1.1' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui l’unità' }))
  expect(screen.queryByRole('group', { name: /Riesegui/ })).not.toBeInTheDocument()
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true }))
})
it('tutto verificato: niente unità mancanti, la ri-verifica globale parte subito', async () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  expect(screen.queryByRole('button', { name: /^Verifica le unità mancanti/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui tutta la lezione' }))
  expect(screen.queryByRole('group', { name: /Riesegui/ })).not.toBeInTheDocument()
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', force: true }))
})
it('le issue si aprono e si chiudono nella propria unità', () => {
  state.units = [unit('1.1', 'issues', 1)]
  mount()
  expect(screen.getByRole('list', { name: 'Issue dell’unità 1.1' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi le issue dell’unità 1.1' }))
  expect(screen.queryByRole('list', { name: 'Issue dell’unità 1.1' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Apri le issue dell’unità 1.1' }))
  expect(screen.getByRole('list', { name: 'Issue dell’unità 1.1' })).toBeInTheDocument()
})
it('claim_changed mostra l’errore nella card e passa a Testo cambiato', async () => {
  state.refetch.mockImplementationOnce(() => { state.items = state.items.map(item => ({ ...item, quote_status: 'changed' })); return Promise.resolve({ data: { items: state.items } }) })
  state.decide.mockRejectedValueOnce(new ApiError(409, 'claim_changed', 'Il testo è già cambiato: modificalo a mano o chiudi l’issue'))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  expect(await screen.findByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Il testo è già cambiato')
})

it('verifica solo le unità cambiate o mai verificate', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Verifica' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', units: ['1.2', '2.1'] }))
})
it('la verifica dell’unità sostituisce la selezione a caselle', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'changed'), unit('2.1', 'never'), unit('2.2', 'never')]
  mount()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: "Verifica l'unità 1.2" }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', unit: '1.2' }))
  expect(screen.queryByRole('button', { name: /^Verifica le selezionate/ })).not.toBeInTheDocument()
})
it.each(['review_unit', 'run_phase'])('il job singolo %s mostra Verifico solo nella sua riga; la riga porta al testo', type => {
  state.units = [unit('1.1', 'never'), unit('1.2', 'ok')]
  state.jobs = [{ id: 'j', type, state: 'running', payload: { phase: 'review', unit: '1.1' }, attempts: 0, cancel_requested: false } as Schemas['Job']]
  const scroll = vi.fn()
  window.addEventListener('rt-editor-scroll', scroll)
  mount()
  expect(screen.getByTestId('review-unit-never')).toHaveTextContent('In corso')
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

it('la riga mostra In coda mentre si accoda il job', async () => {
  state.units = [unit('1.1', 'never')]
  let finish!: () => void
  state.run.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
  mount()
  fireEvent.click(screen.getByRole('button', { name: "Verifica l'unità 1.1" }))
  try { await waitFor(() => expect(screen.getByTestId('review-unit-never')).toHaveTextContent('In coda')) }
  finally { finish() }
})

it('una citazione non ancorata si può soltanto rifiutare', async () => {
  state.items = [{ ...issue, quote_status: 'changed', issue: { ...issue.issue, unanchored: true } }]
  mount(undefined, undefined, 'testo senza la citazione')
  expect(screen.getByText('Non ancorata')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accetta la correzione' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Correzione proposta')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'rejected', text: undefined }))
})

it('il job documenti non blocca decisioni ravvicinate', async () => {
  state.jobs = [{ id: 'doc', state: 'running', type: 'documents', payload: {} } as Schemas['Job']]
  mount()
  const accept = screen.getByRole('button', { name: 'Accetta la correzione' })
  expect(accept).toBeEnabled()
  fireEvent.click(accept)
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
})


it('Verifica conta mai verificate, cambiate e fallite; tooltip e badge coincidono', async () => {
  state.units = [unit('1.1', 'never'), unit('1.2', 'changed'), unit('1.3', 'failed'), unit('2.1', 'excluded'), unit('2.2', 'ok')]
  mount()
  const button = screen.getByRole('button', { name: 'Verifica' })
  expect(button).toHaveTextContent('3')
  fireEvent.mouseEnter(button)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Verifica: 3 unità da verificare')
  fireEvent.mouseLeave(button)
  fireEvent.click(button)
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', units: ['1.1', '1.2', '1.3'] }))
})
it('Verifica senza unità da fare è spenta e spiega il motivo col tooltip', async () => {
  state.units = [unit('1.1', 'ok'), unit('1.2', 'excluded')]
  mount()
  const button = screen.getByRole('button', { name: 'Verifica' })
  expect(button).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(button)
  expect(state.run).not.toHaveBeenCalled()
  fireEvent.mouseEnter(button)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Tutte le unità sono verificate')
})
it('i puntini di gravità contano soltanto le issue aperte', () => {
  state.units = [unit('1.1', 'issues', 2)]
  state.items = [issue, { ...issue, issue: { ...issue.issue, id: 'b', severity: 'low' }, decision: { issue_id: 'b', decision: 'rejected', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount()
  expect(screen.getByLabelText('Gravità alta')).toBeInTheDocument()
  expect(screen.queryByLabelText('Gravità bassa')).not.toBeInTheDocument()
})


it('la card dell’issue è dentro la sua unità e apre la successiva dopo una decisione', async () => {
  state.units = [unit('1.1', 'issues', 1), unit('1.2', 'issues', 1)]
  state.items = [issue, { ...issue, issue: { ...issue.issue, id: 'b', unit_id: '1.2', suggested_fix: 'Seconda correzione.' } }]
  mount()
  expect(screen.getByTestId('issue-detail').closest('[data-unit]')).toHaveAttribute('data-unit', '1.1')
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  await waitFor(() => expect(screen.getByTestId('issue-detail').closest('[data-unit]')).toHaveAttribute('data-unit', '1.2'))
  expect(screen.getByTestId('proposed-correction')).toHaveTextContent('Seconda correzione.')
  expect(screen.getByTestId('review-decision-message')).toHaveTextContent('Correzione accettata.')
  expect(screen.getByRole('button', { name: "Annulla l'ultima decisione" })).not.toHaveAttribute('aria-disabled')
  fireEvent.click(within(screen.getByTestId('review-decision-message')).getByRole('button', { name: 'Annulla' }))
  await waitFor(() => expect(screen.getByTestId('issue-detail').closest('[data-unit]')).toHaveAttribute('data-unit', '1.1'))
  expect(state.undo).toHaveBeenCalledWith('a')
  expect(screen.queryByTestId('review-decision-message')).not.toBeInTheDocument()
})
it('Mostra decise apre una card in sola lettura con la sola azione Annulla', async () => {
  state.items = [{ ...issue, decision: { issue_id: 'a', decision: 'edited', resolved_text: 'Correzione personale.', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount()
  expect(screen.queryByTestId('issue-detail')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  const card = screen.getByTestId('issue-detail')
  expect(card).toHaveTextContent('Correzione personale.')
  expect(within(card).getAllByRole('button')).toHaveLength(1)
  expect(within(card).getByRole('button', { name: 'Annulla' })).toBeInTheDocument()
  fireEvent.doubleClick(within(card).getByTestId('proposed-correction'))
  expect(within(card).queryByRole('textbox')).not.toBeInTheDocument()
  fireEvent.click(within(card).getByRole('button', { name: 'Annulla' }))
  await waitFor(() => expect(state.undo).toHaveBeenCalledWith('a'))
})
it('da riconfermare resta aperta senza Mostra decise e permette una nuova scelta', async () => {
  state.items = [{ ...issue, fix_text: null, needs_reconfirmation: true, decision: { issue_id: 'a', decision: 'accepted', resolved_text: 'Correzione precedente.', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('1 da decidere')
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Da riconfermare')
  expect(screen.getByTestId('proposed-correction')).toHaveTextContent('Correzione precedente.')
  fireEvent.click(screen.getByRole('button', { name: 'Riconferma la correzione' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
})
it('da riconfermare senza passaggio ritrovato permette solo di mantenere il testo', async () => {
  state.items = [{ ...issue, quote_status: 'changed', needs_reconfirmation: true, decision: { issue_id: 'a', decision: 'accepted', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount(undefined, undefined, '## 1. Sezione\n### 1.1 Unità\n00:00\nTesto diverso.')
  expect(screen.queryByRole('button', { name: 'Riconferma la correzione' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'rejected', text: undefined }))
})
it('un avviso di paragrafo si conferma senza modifica e una vecchia decisione resta annullabile', async () => {
  state.items = [{ ...issue, issue: { ...issue.issue, type: 'ERR_ASR_ST' } }]
  const view = mount()
  expect(screen.queryByRole('button', { name: 'Modifica il paragrafo' })).not.toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Ho controllato' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
  view.unmount()
  state.items = [{ ...state.items[0], decision: { issue_id: 'a', decision: 'edited', resolved_text: 'Paragrafo corretto.', timestamp: '2026-10-11', resolved_by: 'user' } }]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  const card = within(screen.getByTestId('issue-detail'))
  expect(card.getByText('modificata')).toBeInTheDocument()
  fireEvent.click(card.getByRole('button', { name: 'Annulla' }))
  await waitFor(() => expect(state.undo).toHaveBeenCalledWith('a'))
})


it('durante la verifica decide e annulla su una unità finita, mentre le altre sono in corso o in coda', async () => {
  state.units = [unit('1.1', 'issues', 1), unit('1.2', 'never'), unit('1.3', 'never')]
  state.jobs = [{ id: 'j', type: 'run_phase', state: 'running', payload: { phase: 'review' }, attempts: 0, cancel_requested: false, progress: { phase: 'review', pending_units: ['1.2', '1.3'], running_units: ['1.2'] } } as Schemas['Job']]
  mount()
  const rows = screen.getByRole('list', { name: 'Unità della verifica' })
  expect(rows.querySelector('[data-unit="1.1"]')).toHaveTextContent('Con issue')
  expect(rows.querySelector('[data-unit="1.2"]')).toHaveTextContent('In corso')
  expect(rows.querySelector('[data-unit="1.3"]')).toHaveTextContent('In coda')
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
  const message = await screen.findByTestId('review-decision-message')
  await waitFor(() => expect(within(message).getByRole('button', { name: 'Annulla' })).toBeEnabled())
  fireEvent.click(within(message).getByRole('button', { name: 'Annulla' }))
  await waitFor(() => expect(state.undo).toHaveBeenCalledWith('a'))
})
it('una issue della unità ancora pendente non si decide', () => {
  state.jobs = [{ id: 'j', type: 'review_unit', state: 'running', payload: { unit: '1.1' }, attempts: 0, cancel_requested: false, progress: { pending_units: ['1.1'], running_units: ['1.1'] } } as Schemas['Job']]
  mount()
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('button', { name: 'Mantieni il testo attuale' })).toHaveAttribute('aria-disabled', 'true')
})
it('il riepilogo sostituisce l’elenco quando tutta la lezione è decisa; Mostra decise lo riapre', () => {
  state.units = [unit('1.1', 'issues', 1)]
  state.items = [{ ...issue, decision: { issue_id: 'a', decision: 'accepted', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount()
  expect(screen.getByTestId('review-summary')).toHaveTextContent('1 accettate')
  expect(screen.queryByRole('list', { name: 'Unità della verifica' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  expect(screen.queryByTestId('review-summary')).not.toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Unità della verifica' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  expect(screen.getByTestId('review-summary')).toBeInTheDocument()
})
it('il job documents segnala l’aggiornamento anche se il vecchio stato build era VALID', () => {
  state.jobs = [{ id: 'doc', state: 'queued', type: 'documents', payload: {} } as Schemas['Job']]
  mount({ rewrite: 'VALID', review: 'VALID', build: 'VALID' })
  expect(screen.getByTestId('documents-status')).toHaveTextContent('Documento in aggiornamento')
})

it('un link a una decisione nascosta conserva l’issue fino a Mostra decise', () => {
  state.items = [{ ...issue, decision: { issue_id: 'a', decision: 'edited', resolved_text: 'Scelta precedente.', resolved_by: 'user', timestamp: '2026-10-10' } }, { ...issue, issue: { ...issue.issue!, id: 'b', suggested_fix: 'Prossima correzione.' } }]
  mount(undefined, undefined, undefined, {}, '/?issue=a')
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Prossima correzione.')
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Scelta precedente.')
  fireEvent.click(screen.getByRole('button', { name: 'Mostra decise' }))
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Prossima correzione.')
})

it.each(['ERR_ASR_ST', 'ERR_REWRITE_DRIFT'])('avviso %s: solo Ho controllato, senza box o matita', async type => {
  state.items = [{ ...issue, quote_status: 'changed', issue: { ...issue.issue, type, claim: 'Trascritto grezzo.' } }]
  mount(undefined, undefined, 'Passaggio riscritto e cambiato.')
  const card = within(screen.getByTestId('issue-detail'))
  expect(card.queryByTestId('proposed-correction')).not.toBeInTheDocument()
  expect(card.queryByRole('button', { name: /Modifica|Mantieni|Accetta/ })).not.toBeInTheDocument()
  expect(card.queryByText('Testo cambiato')).not.toBeInTheDocument()
  fireEvent.click(card.getByRole('button', { name: 'Ho controllato' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledWith({ issueId: 'a', decision: 'accepted', text: undefined }))
})

it('usa solo quote_status: il contesto può differire senza bloccare una citazione found', () => {
  state.items = [{ ...issue, quote_status: 'found', context: { ...issue.context, timecode: '00:00', unit_content: 'Contesto differente.' } }]
  mount()
  expect(within(screen.getByTestId('issue-detail')).queryByText('Testo cambiato')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toBeEnabled()
})

it('quote_status changed offre una verifica immediata dell’unità', async () => {
  state.units = [unit('1.1', 'changed')]
  state.items = [{ ...issue, quote_status: 'changed' }]
  mount()
  expect(within(screen.getByTestId('issue-detail')).getByText('Testo cambiato')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: "Verifica di nuovo l'unità" }))
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true }))
  expect(screen.queryByRole('group', { name: /Riesegui/ })).not.toBeInTheDocument()
})

it('i menu tengono spenta la riesecuzione mai verificata e offrono il bypass', async () => {
  state.units = [{ ...unit('1.1', 'never'), reviewed_at: null }]
  mount({ rewrite: 'VALID', review: 'MISSING' })
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  expect(screen.getByRole('menuitem', { name: /Riesegui tutta la lezione/ })).toHaveAttribute('aria-disabled', 'true')
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Azioni sull’unità 1.1' }))
  expect(screen.getByRole('menuitem', { name: /Riesegui l’unità/ })).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(screen.getByRole('menuitem', { name: 'Esegui senza classificatore' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true, skip_prefilter: true }))
})
it('il bypass di una unità esclusa conserva il classificatore e ignora solo la sua esclusione', async () => {
  state.units = [unit('1.1', 'excluded')]
  mount({ rewrite: 'VALID', review: 'MISSING' })
  expect(screen.getByRole('button', { name: 'Apri il Classificatore' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni sull’unità 1.1' }))
  expect(screen.queryByRole('menuitem', { name: /Riesegui/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Esegui senza classificatore' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true, skip_prefilter: true, include_excluded: true }))
})
it('il bypass globale lascia fuori le escluse anche dalla coda', async () => {
  state.units = [unit('1.1', 'issues'), unit('1.2', 'excluded')]
  state.run.mockImplementationOnce(() => new Promise(() => {}))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Esegui senza classificatore' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledExactlyOnceWith({ type: 'run_phase', phase: 'review', force: true, skip_prefilter: true }))
  expect(within(screen.getByTestId('review-unit-issues')).getByRole('img', { name: 'In coda' })).toBeInTheDocument()
  expect(within(screen.getByTestId('review-unit-excluded')).queryByRole('img', { name: 'In coda' })).not.toBeInTheDocument()
})

it('l’icona dell’ordine passa da orologio a gravità col pulsante', () => {
  mount()
  const button = screen.getByRole('button', { name: 'Ordine delle issue' })
  expect(button.querySelector('svg')).toHaveClass('lucide-clock')
  fireEvent.click(button)
  expect(button.querySelector('svg')).toHaveClass('lucide-triangle-alert')
  fireEvent.click(button)
  expect(button.querySelector('svg')).toHaveClass('lucide-clock')
})
it('l’avviso della decisione sale dal basso con la barra dei 5 s e poi sparisce; l’ultima decisione resta annullabile dall’intestazione', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    mount()
    const header = screen.getByRole('button', { name: "Annulla l'ultima decisione" })
    expect(header).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(header)
    expect(state.undo).not.toHaveBeenCalled()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Accetta la correzione' })) })
    const toast = screen.getByTestId('review-decision-message')
    expect(toast).toHaveTextContent('Correzione accettata.')
    expect(within(toast).getByTestId('review-decision-timer')).toBeInTheDocument()
    expect(toast.closest('[data-testid="lesson-review-panel"]')).toBeNull()
    act(() => { vi.advanceTimersByTime(4900) })
    expect(screen.getByTestId('review-decision-message')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(200) })
    expect(screen.queryByTestId('review-decision-message')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: "Annulla l'ultima decisione" })).not.toHaveAttribute('aria-disabled'))
    fireEvent.click(screen.getByRole('button', { name: "Annulla l'ultima decisione" }))
    await waitFor(() => expect(state.undo).toHaveBeenCalledWith('a'))
    await waitFor(() => expect(screen.getByRole('button', { name: "Annulla l'ultima decisione" })).toHaveAttribute('aria-disabled', 'true'))
  } finally { vi.useRealTimers() }
})
it('l’avviso resta mentre il puntatore ci passa sopra', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    mount()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Mantieni il testo attuale' })) })
    const toast = screen.getByTestId('review-decision-message')
    fireEvent.mouseEnter(toast)
    act(() => { vi.advanceTimersByTime(8000) })
    expect(screen.getByTestId('review-decision-message')).toBeInTheDocument()
    fireEvent.mouseLeave(toast)
    act(() => { vi.advanceTimersByTime(5100) })
    expect(screen.queryByTestId('review-decision-message')).not.toBeInTheDocument()
  } finally { vi.useRealTimers() }
})
it('la card non mostra l’unità e Ascolta è un pulsante a icona accanto ad accetta e mantieni', () => {
  mount(undefined, undefined, undefined, { has_audio: true })
  const card = screen.getByTestId('issue-detail')
  expect(card).not.toHaveTextContent('Unità')
  const listen = within(card).getByRole('button', { name: 'Ascolta da 00:00' })
  expect(listen.textContent).toBe('')
  expect(listen.parentElement).toBe(within(card).getByRole('button', { name: 'Accetta la correzione' }).parentElement)
  fireEvent.click(listen)
})
it('senza istante o senza audio non c’è il pulsante Ascolta', () => {
  state.items = [{ ...issue, context: { timecode: '00:00', unit_content: 'Il pH è 6.' } }]
  mount(undefined, undefined, undefined, { has_audio: true })
  expect(screen.queryByRole('button', { name: /^Ascolta da/ })).not.toBeInTheDocument()
})
it('Accetta tutte chiede conferma, accetta solo le correzioni applicabili e l’annullamento le riporta tutte', async () => {
  state.units = [unit('1.1', 'issues', 3), unit('1.2', 'issues', 1)]
  state.items = [issue, { ...issue, issue: { ...issue.issue, id: 'b', unit_id: '1.2' } }, { ...issue, issue: { ...issue.issue, id: 'c', type: 'ERR_ASR_ST' } }, { ...issue, quote_status: 'changed', issue: { ...issue.issue, id: 'd' } }, { ...issue, fix_text: null, issue: { ...issue.issue, id: 'e' } }]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta tutte le correzioni da decidere (2)' }))
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Accetta tutte le correzioni' })).getByRole('button', { name: 'Annulla' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Accetta tutte le correzioni da decidere (2)' }))
  const dialog = screen.getByRole('dialog', { name: 'Accetta tutte le correzioni' })
  expect(state.decide).not.toHaveBeenCalled()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Accetta 2' }))
  await waitFor(() => expect(state.decide).toHaveBeenCalledTimes(2))
  expect(state.decide.mock.calls.map(([body]) => body)).toEqual([{ issueId: 'a', decision: 'accepted' }, { issueId: 'b', decision: 'accepted' }])
  expect(await screen.findByTestId('review-decision-message')).toHaveTextContent('2 correzioni accettate.')
  fireEvent.click(screen.getByRole('button', { name: "Annulla l'ultima decisione" }))
  await waitFor(() => expect(state.undo).toHaveBeenCalledTimes(2))
  expect(state.undo.mock.calls.map(([id]) => id)).toEqual(['b', 'a'])
})
it('Accetta tutte è spenta senza correzioni da decidere', () => {
  state.items = [{ ...issue, decision: { issue_id: 'a', decision: 'accepted', resolved_by: 'user', timestamp: '2026-10-10' } }]
  mount()
  expect(screen.getByRole('button', { name: 'Accetta tutte le correzioni da decidere (0)' })).toHaveAttribute('aria-disabled', 'true')
})

it('resta sulla stessa issue se la decisione appena presa richiede ancora riconferma', async () => {
  const previous: Schemas['Decision'] = { issue_id: 'a', decision: 'accepted', resolved_by: 'user', timestamp: '2026-10-20' }
  const recorded: Schemas['Decision'] = { ...previous, timestamp: '2026-10-21' }
  state.items = [
    { ...issue, needs_reconfirmation: true, decision: previous },
    { ...issue, issue: { ...issue.issue, id: 'b', claim: 'Seconda issue', suggested_fix: 'Altra correzione.' }, needs_reconfirmation: true, decision: { ...previous, issue_id: 'b' } },
  ]
  state.decide.mockImplementationOnce(async () => {
    state.items = state.items.map(item => item.issue.id === 'a' ? { ...item, decision: recorded } : item)
    return recorded
  })
  state.refetch.mockImplementationOnce(async () => ({ data: { items: state.items } }))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Riconferma la correzione' }))
  expect(await screen.findByRole('alert')).toHaveTextContent("La decisione non si applica: l'unità non c'è più.")
  expect(screen.getByTestId('issue-detail')).toHaveTextContent('Il pH è 7.')
  expect(screen.getByRole('status')).toHaveTextContent('2 da decidere')
  expect(state.decide).toHaveBeenCalledExactlyOnceWith({ issueId: 'a', decision: 'accepted', text: undefined })
})

it('una issue con $x^2$ nella correzione e nella spiegazione rende MathML e il doppio clic apre Textarea col testo grezzo', async () => {
  const mathIssue: Schemas['IssueItem'] = {
    quote_status: 'found',
    needs_reconfirmation: false,
    issue: {
      id: 'math-issue',
      type: 'ERR_CONCETTUALE',
      severity: 'high',
      unit_id: '1.1',
      claim: 'La funzione vale $x$.',
      suggested_fix: 'La funzione vale $x^2$.',
      reason: 'L’esponente corretto è $x^2$.',
    },
    context: { timecode: '00:00', start_s: 0, unit_content: 'La funzione vale $x$.' },
  }
  state.items = [mathIssue]
  const { container } = mount()

  // Aspetta che Temml generi gli elementi math
  await waitFor(() => {
    const mathElements = container.querySelectorAll('math')
    expect(mathElements.length).toBeGreaterThanOrEqual(2)
  })

  // Nessun $ visibile nella correzione proposta
  const correctionEl = screen.getByTestId('proposed-correction')
  expect(correctionEl.querySelector('math')).not.toBeNull()
  expect(correctionEl.textContent).not.toContain('$')

  // Doppio clic apre il Textarea con il testo grezzo
  fireEvent.doubleClick(correctionEl)
  const textarea = screen.getByRole('textbox', { name: 'Correzione proposta' })
  expect(textarea).toBeInTheDocument()
  expect(textarea).toHaveValue('La funzione vale $x^2$.')
})

