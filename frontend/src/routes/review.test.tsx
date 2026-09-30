import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { ApiError } from '@/api/client'
import { ReviewPage } from './review'

type Item = { issue: Record<string, unknown>; decision?: { decision: string } | null; context?: { start_s?: number; timecode?: string; unit_content?: string } }
type MutateOptions = { onSuccess?: () => void }

const state = vi.hoisted(() => ({
  items: [] as unknown[],
  decisions: [] as unknown[],
  jobs: [] as unknown[],
  decide: vi.fn(),
  undo: vi.fn(),
  decideError: null as unknown,
}))

vi.mock('@/api/hooks', () => ({
  useLesson: () => ({ isPending: false, isError: false, data: { id: 5, titolo: 'Il rene', folder_name: 'rene', materia: 'FISIOLOGIA', has_audio: false } }),
  useLessonDocument: () => ({ data: undefined }),
  useIssues: () => ({
    isPending: false,
    isError: false,
    data: { items: state.items, pending: (state.items as Item[]).filter((i) => !i.decision).length, total: state.items.length },
  }),
  useDecisions: () => ({ data: state.decisions }),
  useLessonJobs: () => ({ data: state.jobs }),
  useDecideIssue: () => ({ mutate: state.decide, isPending: false, isError: state.decideError != null, error: state.decideError }),
  useUndoDecision: () => ({ mutate: state.undo, isPending: false, isError: false }),
}))
vi.mock('@/components/lesson/DocumentView', () => ({ DocumentView: () => null }))
vi.mock('@/components/lesson/AudioPlayer', () => ({ AudioPlayer: () => null }))

const item = (id: string, type: string, severity: string, start: number, decided = false): Item => ({
  issue: { id, type, severity, claim: `Affermazione ${id}`, reason: `Motivo ${id}`, suggested_fix: `Correzione ${id}` },
  decision: decided ? { decision: 'accepted' } : null,
  context: { start_s: start, timecode: `0:${start}` },
})

function renderReview(query = '') {
  render(
    <MemoryRouter initialEntries={[`/lezioni/5/revisione${query}`]}>
      <Routes>
        <Route path="/lezioni/:lessonId/revisione" element={<ReviewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const selected = () => screen.getByTestId('issue-detail').getAttribute('data-issue-id')
const listed = (group: string) => within(screen.getByRole('list', { name: group })).getAllByRole('button').map((b) => b.getAttribute('data-issue'))

beforeEach(() => {
  state.items = [
    item('asr', 'ERR_ASR_ST', 'low', 10),
    item('medio', 'ERR_CONCETTUALE', 'medium', 50),
    item('grave', 'ERR_CONCETTUALE', 'high', 90),
    item('fatta', 'IMPRECISIONE', 'low', 5, true),
  ]
  state.decisions = []
  state.jobs = []
  state.decideError = null
  state.decide.mockReset()
  state.undo.mockReset()
  // mutate "riuscito": come react-query, chiama onSuccess.
  state.decide.mockImplementation((_body: unknown, options?: MutateOptions) => options?.onSuccess?.())
  state.undo.mockImplementation((_id: unknown, options?: MutateOptions) => options?.onSuccess?.())
})

describe('ReviewPage', () => {
  it('elenca da decidere e decise in ordine cronologico e apre la prima da decidere', () => {
    renderReview()
    expect(screen.getByTestId('review-counter')).toHaveTextContent('3 da decidere su 4')
    expect(listed('Da decidere')).toEqual(['asr', 'medio', 'grave'])
    expect(listed('Decise')).toEqual(['fatta'])
    expect(selected()).toBe('asr')
    expect(screen.getByRole('button', { name: /Annulla ultima/ })).toBeDisabled()
  })

  it("l'ordine per tipo e gravità mette prima gli errori concettuali gravi", () => {
    renderReview()
    fireEvent.click(screen.getByRole('button', { name: 'Tipo e gravità' }))
    expect(screen.getByRole('button', { name: 'Tipo e gravità' })).toHaveAttribute('aria-pressed', 'true')
    expect(listed('Da decidere')).toEqual(['grave', 'medio', 'asr'])
    expect(selected()).toBe('grave')
  })

  it('accettare una issue passa alla successiva da decidere', () => {
    renderReview('?issue=medio')
    expect(selected()).toBe('medio')
    fireEvent.click(screen.getByRole('button', { name: /Accetta correzione/ }))
    expect(state.decide).toHaveBeenCalledWith({ issueId: 'medio', decision: 'accepted', text: undefined }, expect.anything())
    expect(selected()).toBe('grave')
  })

  it("con la tastiera: R mantiene l'originale, le frecce navigano, E apre la modifica", () => {
    renderReview('?issue=medio')
    fireEvent.keyDown(document.body, { key: 'r' })
    expect(state.decide).toHaveBeenLastCalledWith({ issueId: 'medio', decision: 'rejected', text: undefined }, expect.anything())
    expect(selected()).toBe('grave')
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    expect(selected()).toBe('medio')
    fireEvent.keyDown(document.body, { key: 'e' })
    const editor = screen.getByLabelText('Testo corretto')
    expect(editor).toHaveValue('Correzione medio')
    // Mentre si scrive le scorciatoie non scattano.
    fireEvent.keyDown(editor, { key: 'a' })
    fireEvent.change(editor, { target: { value: 'Testo mio' } })
    expect(state.decide).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Salva modifica' }))
    expect(state.decide).toHaveBeenLastCalledWith({ issueId: 'medio', decision: 'edited', text: 'Testo mio' }, expect.anything())
  })

  it("decisa l'ultima issue, con una pipeline in attesa dice che è ripartita", () => {
    state.items = [item('sola', 'IMPRECISIONE', 'low', 1)]
    state.jobs = [{ id: 'j', state: 'waiting_for_decision' }]
    renderReview()
    fireEvent.click(screen.getByRole('button', { name: /Mantieni originale/ }))
    expect(screen.getByTestId('review-notice')).toHaveTextContent('la pipeline in attesa è ripartita')
  })

  it("decisa l'ultima issue, senza job in attesa rimanda al documento finale", () => {
    state.items = [item('sola', 'IMPRECISIONE', 'low', 1)]
    renderReview()
    fireEvent.click(screen.getByRole('button', { name: /Accetta correzione/ }))
    expect(screen.getByTestId('review-notice')).toHaveTextContent('generare il documento finale')
  })

  it("Annulla ultima annulla la decisione più recente fra le issue della lezione e la riapre", () => {
    state.decisions = [
      { issue_id: 'fatta', timestamp: '2026-09-20T10:00:00Z' },
      { issue_id: 'asr', timestamp: '2026-09-20T09:00:00Z' },
      { issue_id: 'altra-lezione', timestamp: '2026-09-20T11:00:00Z' },
    ]
    renderReview()
    fireEvent.click(screen.getByRole('button', { name: /Annulla ultima/ }))
    expect(state.undo).toHaveBeenCalledWith('fatta', expect.anything())
    expect(selected()).toBe('fatta')
  })

  it("un'issue di qualità ASR si accetta come paragrafo: niente correzione proposta né Mantieni originale", () => {
    state.items = [{ ...item('asr', 'ERR_ASR_ST', 'low', 10), context: { start_s: 10, timecode: '0:10', unit_content: 'Paragrafo intero.' } }]
    renderReview()
    expect(screen.queryByTestId('issue-suggestion')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mantieni originale/ })).not.toBeInTheDocument()
    fireEvent.keyDown(document.body, { key: 'r' })
    expect(state.decide).not.toHaveBeenCalled()
    // Modifica parte dall'intero paragrafo, che la decisione sostituisce per intero.
    fireEvent.keyDown(document.body, { key: 'e' })
    expect(screen.getByLabelText('Testo del paragrafo')).toHaveValue('Paragrafo intero.')
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
    fireEvent.click(screen.getByRole('button', { name: /Accetta paragrafo/ }))
    expect(state.decide).toHaveBeenCalledWith({ issueId: 'asr', decision: 'accepted', text: undefined }, expect.anything())
  })

  it('a revisione finita il pannello di decisione si chiude e si riapre dalla lista', () => {
    state.items = [item('sola', 'IMPRECISIONE', 'low', 1)]
    // Come dopo il refetch: l'issue risulta decisa.
    state.decide.mockImplementation((_body: unknown, options?: MutateOptions) => {
      state.items = [item('sola', 'IMPRECISIONE', 'low', 1, true)]
      options?.onSuccess?.()
    })
    renderReview()
    fireEvent.click(screen.getByRole('button', { name: /Accetta correzione/ }))
    expect(screen.queryByTestId('issue-detail')).not.toBeInTheDocument()
    expect(screen.getByTestId('review-complete')).toBeInTheDocument()
  })

  it('tornando su una revisione finita non apre l’ultima decisa, ma la si può riaprire', () => {
    state.items = [item('fatta', 'IMPRECISIONE', 'low', 5, true)]
    renderReview()
    expect(screen.queryByTestId('issue-detail')).not.toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('list', { name: 'Decise' })).getByRole('button'))
    expect(selected()).toBe('fatta')
  })

  it('se la lezione è occupata da un job lo spiega', () => {
    state.decideError = new ApiError(409, 'lesson_busy', 'occupata')
    renderReview()
    expect(screen.getByText(/Sulla lezione sta lavorando un job/)).toBeInTheDocument()
  })
})
