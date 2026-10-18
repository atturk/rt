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

const phases = vi.hoisted(() => ({ list: [] as Record<string, unknown>[] }))
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
  usePhases: () => ({ data: { phases: phases.list } }),
  useUpdateLessonMetadata: () => ({ mutate: mutateMetadata, isPending: false, isError: false }),
  usePipelineVersion: () => ({ data: pipelineVersion }),
  useRestorePipeline: () => ({ mutate: mutateRestore, isPending: false, isError: false }),
  useDeleteLesson: () => ({ mutate: mutateDelete, isPending: false, isError: false }),
}))

beforeEach(() => {
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
