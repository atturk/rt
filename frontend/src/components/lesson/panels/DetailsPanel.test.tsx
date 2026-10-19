vi.mock('@/api/classifier', () => ({ useClassifier: () => ({ data: { pending: 2 } }) }))
vi.mock('./SourcesSection', () => ({ SourcesSection: () => <div data-testid="sources-section" /> }))
import { fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { DetailsPanel } from './DetailsPanel'

const mutateRun = vi.fn()
const mutateValidate = vi.fn()
const mutateMetadata = vi.fn()
const mutateRestore = vi.fn()
const mutateDelete = vi.fn()

const phases = vi.hoisted(() => ({ list: [] as Record<string, unknown>[], outline_validation: null as Record<string, unknown> | null, draft_validation: null as Record<string, unknown> | null }))
const sourceState = vi.hoisted(() => ({ available: true, reason: null as string | null, mutate: vi.fn(), start: vi.fn(), running: false }))
vi.mock('@/api/sources', () => ({ useSources: () => ({ data: { reingest_available: sourceState.available, reingest_reason: sourceState.reason } }), useUpdateLesson: () => ({ mutate: sourceState.mutate, isPending: false, isError: false }), useSourcesJob: () => ({ start: sourceState.start, running: sourceState.running, error: null }) }))
const pipelineVersion = vi.hoisted(() => ({ available: true, modified_units: 3 }))

vi.mock('@/api/jobs', () => ({
  useOutline: () => ({
    data: {
      macro_sections: [
        {
          units: [
            { id: '1.1', title: 'Uno' },
            { id: '1.2', title: 'Due' },
          ],
        },
      ],
    },
  }),
}))

vi.mock('@/api/subjects', () => ({
  useTeacherSuggestions: (materia: string) => materia === 'ANATOMIA' ? ['Bianchi'] : ['Rossi'],
  useSubjects: () => ({
    data: [
      { nome: 'FISIOLOGIA', lezioni: 1 },
      { nome: 'ANATOMIA', lezioni: 0 },
    ],
  }),
}))

vi.mock('@/api/hooks', () => ({
  isActiveJob: () => false,
  useLessonJobs: () => ({ data: [] }),
  useLessons: () => ({ data: [] }),
  useWorkers: () => ({ data: [{}] }),
  useRunJob: () => ({ mutate: mutateRun, isPending: false }),
  useValidatePhase: () => ({ mutate: mutateValidate, reset: vi.fn(), isPending: false, isError: false }),
  usePhases: () => ({ data: { phases: phases.list, outline_validation: phases.outline_validation, draft_validation: phases.draft_validation } }),
  useUpdateLessonMetadata: () => ({ mutate: mutateMetadata, isPending: false, isError: false }),
  usePipelineVersion: () => ({ data: pipelineVersion }),
  useRestorePipeline: () => ({ mutate: mutateRestore, isPending: false, isError: false }),
  useDeleteLesson: () => ({ mutate: mutateDelete, isPending: false, isError: false }),
}))

beforeEach(() => {
  phases.outline_validation = null
  phases.draft_validation = null
  sourceState.available = true
  sourceState.reason = null
  sourceState.mutate.mockReset()
  sourceState.start.mockReset()
  sourceState.running = false
  phases.list = [
    { phase: 'prepare', status: 'VALID', reason: '' },
    { phase: 'outline', status: 'VALID', reason: '' },
    { phase: 'rewrite', status: 'VALID', reason: '' },
    { phase: 'review', status: 'VALID', reason: '' },
    { phase: 'build', status: 'VALID', reason: '' },
  ]
  pipelineVersion.available = true
  pipelineVersion.modified_units = 3
  mutateRun.mockReset()
  mutateValidate.mockReset()
  mutateMetadata.mockReset()
  mutateRestore.mockReset()
  mutateDelete.mockReset()
})

const sampleLesson = {
  id: 1,
  titolo: 'Emogasanalisi e acidosi',
  materia: 'FISIOLOGIA',
  data: '2026-10-02',
  ora: '10:30',
  docente: 'Rossi',
  folder_name: '[2026-10-02] FISIOLOGIA - Emogasanalisi e acidosi',
  state: 'completato',
  duration_seconds: 4800,
  cost_usd: 0.84,
  pending_issues: 0,
  phases: {
    prepare: 'VALID',
    outline: 'VALID',
    rewrite: 'VALID',
    review: 'VALID',
    build: 'VALID',
  },
} as never

const row = (phase: string) => document.querySelector(`[data-phase-row=${phase}]`) as HTMLElement

describe('DetailsPanel', () => {
  it('mostra metadati e chiama la patch alla modifica', () => {
    render(
      <MemoryRouter>
        <DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} />
      </MemoryRouter>,
    )

    const titleInput = screen.getByLabelText('Titolo')
    expect(titleInput).toHaveValue('Emogasanalisi e acidosi')

    fireEvent.change(titleInput, { target: { value: 'Nuovo Titolo' } })
    fireEvent.blur(titleInput)

    expect(mutateMetadata).toHaveBeenCalledWith(
      expect.objectContaining({
        titolo: 'Nuovo Titolo',
      }),
    )
  })

  it('la materia si può spostare anche su una materia senza lezioni', () => {
    render(
      <MemoryRouter>
        <DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} />
      </MemoryRouter>,
    )

    const select = screen.getByLabelText('Materia')
    const options = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['ANATOMIA', 'FISIOLOGIA'])

    fireEvent.change(select, { target: { value: 'ANATOMIA' } })
    expect(mutateMetadata).toHaveBeenCalledWith(expect.objectContaining({ materia: 'ANATOMIA' }))
  })

  it('il menu delle fasi permette di aprire le opzioni avanzate ed eseguire con unità', () => {
    render(
      <MemoryRouter>
        <DetailsPanel
          lesson={sampleLesson}
          sections={[{ unit_id: '1.1', title: 'Uno' } as never]}
          editingDocument={false}
        />
      </MemoryRouter>,
    )

    const rewriteRow = row('rewrite')
    const menuBtn = within(rewriteRow).getByRole('button', { name: /Azioni su Rielaborazione/i })
    fireEvent.click(menuBtn)

    // Il menu sta in un portale fuori dal pannello (non viene tagliato in fondo).
    const menu = screen.getByRole('menu', { name: 'Azioni su Rielaborazione' })
    expect(rewriteRow).not.toContainElement(menu)
    const optionsItem = within(menu).getByRole('menuitem', { name: /Riesegui con opzioni/i })
    fireEvent.click(optionsItem)

    // Opzioni aperte in un popup, con l'elenco delle unità che tronca i titoli lunghi
    const dialog = screen.getByRole('dialog', { name: 'Riesegui rielaborazione' })
    expect(rewriteRow).not.toContainElement(dialog)
    const checkbox12 = within(dialog).getByLabelText('1.2 Due')
    expect(checkbox12.closest('label')).toHaveClass('min-w-0')
    expect(within(dialog).getByLabelText('Istruzioni aggiuntive')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('anche se è già valida')).toBeInTheDocument()
    fireEvent.click(checkbox12)

    const runBtn = screen.getByRole('button', { name: /Riesegui 1 unità/i })
    fireEvent.click(runBtn)

    expect(mutateRun).toHaveBeenCalledWith(
      expect.objectContaining({
        phase: 'rewrite',
        units: ['1.2'],
      }),
      expect.anything(),
    )
  })

  it('il menu permette di validare a mano una fase STALE con conferma', () => {
    phases.list = [
      { phase: 'outline', status: 'STALE', reason: 'segments.json modificato' },
      { phase: 'rewrite', status: 'VALID', reason: '' },
      { phase: 'review', status: 'VALID', reason: '' },
      { phase: 'build', status: 'VALID', reason: '' },
    ]

    render(
      <MemoryRouter>
        <DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} />
      </MemoryRouter>,
    )

    const outlineRow = row('outline')
    const menuBtn = within(outlineRow).getByRole('button', { name: /Azioni su Scaletta/i })
    fireEvent.click(menuBtn)

    const validateItem = screen.getByRole('menuitem', { name: /Segna come valida/i })
    expect(validateItem).not.toHaveAttribute('aria-disabled')
    fireEvent.click(validateItem)

    expect(screen.getByText(/senza eseguirla di nuovo/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Valida' }))

    expect(mutateValidate).toHaveBeenCalledWith('outline', expect.anything())
  })

  it('mostra il ripristino della pipeline e permette di ripristinare', () => {
    render(
      <MemoryRouter>
        <DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} />
      </MemoryRouter>,
    )

    const restoreBtn = screen.getByRole('button', { name: /Ripristina la versione della pipeline/i })
    fireEvent.click(restoreBtn)

    expect(screen.getByText(/Ripristinare la versione della pipeline\?/i)).toBeInTheDocument()
    expect(screen.getByText(/Modificate a mano: 3 unità/i)).toBeInTheDocument()

    const confirmBtn = screen.getByRole('button', { name: /^Ripristina$/i })
    fireEvent.click(confirmBtn)

    expect(mutateRestore).toHaveBeenCalled()
  })

  it('chiede la conferma confermo per eliminare la lezione', () => {
    render(
      <MemoryRouter>
        <DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} />
      </MemoryRouter>,
    )

    const deleteBtn = screen.getByRole('button', { name: /Elimina la lezione/i })
    fireEvent.click(deleteBtn)

    const input = screen.getByLabelText(/Scrivi confermo/i)
    const submitBtn = screen.getByRole('button', { name: /^Elimina$/i })
    expect(submitBtn).toBeDisabled()

    fireEvent.change(input, { target: { value: 'confermo' } })
    expect(submitBtn).toBeEnabled()

    fireEvent.click(submitBtn)
    expect(mutateDelete).toHaveBeenCalled()
  })
})

it('il documento si aggiorna da solo: nessuna azione di build nei Dettagli', () => {
  phases.list = [{ phase: 'build', status: 'STALE', reason: 'Testo cambiato' }]
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  expect(row('build')).toHaveTextContent('in aggiornamento')
  expect(within(row('build')).queryByRole('button')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Ricrea' })).not.toBeInTheDocument()
  expect(mutateRun).not.toHaveBeenCalled()
})

it('Segna come valida resta nel menu ma non è disponibile su una fase già valida', () => {
  phases.list = [{ phase: 'outline', status: 'VALID', reason: '' }]
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  fireEvent.click(within(row('outline')).getByRole('button', { name: /Azioni su Scaletta/i }))
  expect(screen.getByRole('menuitem', { name: /Segna come valida/i })).toHaveAttribute('aria-disabled', 'true')
})


it('Play esegue solo le fasi necessarie e l’interruttore della revisione vale per la pipeline', () => {
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  expect(screen.queryByText('Pipeline completa')).toBeNull()
  expect(screen.queryByText('con la revisione')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Includi la revisione scientifica' }))
  expect(screen.getByRole('button', { name: 'Includi la revisione scientifica' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Esegui la pipeline' }))
  expect(mutateRun).toHaveBeenCalledWith(expect.objectContaining({ type: 'run_pipeline', force: false, with_review: true }), expect.anything())
})

it('la pipeline forzata parte soltanto dopo la conferma e usa force', () => {
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui tutte le fasi' }))
  expect(mutateRun).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog', { name: 'Rifare tutte le fasi?' })).toHaveTextContent("con il loro costo")
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui' }))
  expect(mutateRun).toHaveBeenCalledWith(expect.objectContaining({ type: 'run_pipeline', force: true }), expect.anything())
})

it('da capo chiede conferma e passa rilettura fonti e revisione al job esistente', () => {
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Includi la revisione scientifica' }))
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui tutto da capo' }))
  expect(sourceState.mutate).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog', { name: 'Rieseguire tutto da capo?' })).toHaveTextContent('note di studio')
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui' }))
  expect(sourceState.mutate).toHaveBeenCalledWith({ mode: 'rebuild', reingest: true, with_review: true }, expect.objectContaining({ onSuccess: expect.any(Function) }))
  sourceState.mutate.mock.calls[0][1].onSuccess({ job_id: 'nuovo-job' })
  expect(sourceState.start).toHaveBeenCalledWith('nuovo-job')
  expect(mutateRun).not.toHaveBeenCalled()
})

it('tutte le azioni sono indisponibili durante la modifica del documento', () => {
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument /></MemoryRouter>)
  for (const label of ['Includi la revisione scientifica', 'Esegui la pipeline', 'Riesegui tutte le fasi', 'Riesegui tutto da capo']) {
    const button = screen.getByRole('button', { name: label })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(button)
  }
  expect(mutateRun).not.toHaveBeenCalled()
  expect(sourceState.mutate).not.toHaveBeenCalled()
})

it('da capo spiega perché un originale mancante lo rende indisponibile', async () => {
  sourceState.available = false
  sourceState.reason = 'Audio originale non disponibile.'
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  const button = screen.getByRole('button', { name: 'Riesegui tutto da capo' })
  expect(button).toHaveAttribute('aria-disabled', 'true')
  fireEvent.mouseEnter(button)
  fireEvent.focus(button)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Audio originale non disponibile.')
  fireEvent.click(button)
  expect(sourceState.mutate).not.toHaveBeenCalled()
})

it.each([true, false])('la validazione %s sta sulla fase e apre dettagli richiudibili', valid => {
  phases.outline_validation = { valid, macro_count: 3, units_count: 7 }
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  const button = screen.getByTestId('validation-outline')
  expect(row('outline')).toContainElement(button)
  expect(button).toHaveAccessibleName(valid ? 'Scaletta valida' : 'Scaletta non valida: apri per i dettagli')
  expect(button.querySelector('svg')).toHaveClass(valid ? 'lucide-shield-check' : 'lucide-shield-alert')
  expect(screen.queryByText('Validazione scaletta')).toBeNull()
  expect(screen.queryByTestId('validation-draft')).toBeNull()
  fireEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('dialog')).toHaveTextContent('Macro-sezioni3Unità7')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(button).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(button)
  fireEvent.pointerDown(document.body)
  expect(button).toHaveAttribute('aria-expanded', 'false')
})


it('le azioni restano indisponibili finché il job da capo non termina', () => {
  sourceState.running = true
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  for (const label of ['Includi la revisione scientifica', 'Esegui la pipeline', 'Riesegui tutte le fasi', 'Riesegui tutto da capo']) {
    expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-disabled', 'true')
  }
})

it('i suggerimenti dei docenti seguono la materia nei Dettagli', () => {
  render(<MemoryRouter><DetailsPanel lesson={sampleLesson} sections={[]} editingDocument={false} /></MemoryRouter>)
  const teacher = screen.getByLabelText('Docente')
  const list = document.getElementById(teacher.getAttribute('list')!)!
  expect(list.querySelector('option')).toHaveValue('Rossi')
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'ANATOMIA' } })
  expect(list.querySelector('option')).toHaveValue('Bianchi')
})
