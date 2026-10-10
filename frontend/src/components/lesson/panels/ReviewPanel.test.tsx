import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
it('passaggio cambiato: chiude l\'issue, ma le decisioni restano possibili', async () => {
  mount(undefined, undefined, '## 1. Sezione\n### 1.1 Unità\n00:00\nIl pH è 7.')
  expect(within(screen.getByTestId('issue-detail')).getByText('Testo cambiato')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Accetta la correzione' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: "Chiudi l'issue" }))
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
  ['PARTIAL', 'Mai verificata', ['ok', 'changed', 'never'], ['1.2', '1.3']],
  ['STALE', 'Mai verificata', ['ok', 'changed', 'failed'], ['1.2', '1.3']],
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

it('testo cambiato: verifica globale solo dal menu con conferma nel pannello', async () => {
  mount({ rewrite: 'VALID', review: 'STALE', build: 'STALE' })
  expect(screen.queryByRole('button', { name: 'Ricostruisci il documento' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui tutta la lezione…' }))
  expect(state.run).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui tutte le unità' }))
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
it('la ri-verifica di una unità chiede conferma e forza solo quella', async () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni sull’unità 1.1' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui l’unità' }))
  expect(state.run).not.toHaveBeenCalled()
  expect(screen.getByRole('group', { name: 'Riesegui l’unità 1.1' })).toHaveTextContent('Le decisioni restano registrate')
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui l’unità' }))
  await waitFor(() => expect(state.run).toHaveBeenCalledWith({ type: 'run_phase', phase: 'review', unit: '1.1', force: true }))
})
it('tutto verificato: niente unità mancanti, la ri-verifica globale chiede conferma', () => {
  state.units = [unit('1.1', 'ok')]
  mount()
  expect(screen.queryByRole('button', { name: /^Verifica le unità mancanti/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Azioni della verifica' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Riesegui tutta la lezione…' }))
  expect(screen.getByRole('group', { name: 'Riesegui tutta la lezione' })).toHaveTextContent('comprese quelle già verificate')
  fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(state.run).not.toHaveBeenCalled()
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
  fireEvent.click(screen.getByRole('button', { name: "Verifica l'unità 1.1" }))
  try { await waitFor(() => expect(screen.getByText('Verifico…')).toBeInTheDocument()) }
  finally { finish() }
})

it('una citazione non ancorata si può soltanto rifiutare', async () => {
  state.items = [{ ...issue, issue: { ...issue.issue, unanchored: true } }]
  mount(undefined, undefined, 'testo senza la citazione')
  expect(screen.getByText('Non ancorata')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accetta la correzione' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Correzione proposta')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Rifiuta' }))
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
