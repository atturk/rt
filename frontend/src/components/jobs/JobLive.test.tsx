import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { JobLive } from './JobLive'

const state = vi.hoisted(() => ({
  job: { isPending: false, isError: false, data: undefined as unknown },
  events: [] as unknown[],
  status: 'open',
  cancel: vi.fn(),
  close: vi.fn(),
}))

vi.mock('@/api/jobs', () => ({
  useJob: () => state.job,
  useJobEvents: () => ({ events: state.events, status: state.status }),
  useCancelJob: () => ({ mutate: state.cancel, isPending: false, isError: false }),
  useCloseJob: () => ({ mutate: state.close, reset: vi.fn(), isPending: false, isError: false }),
  useRetryJob: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}))
vi.mock('@/api/hooks', () => ({
  useLessons: () => ({ data: [{ id: 3, titolo: 'Il rene', materia: 'FISIOLOGIA', data: '2026-09-20' }] }),
}))

function renderJob(job: Record<string, unknown>, compact = false) {
  state.job = { isPending: false, isError: false, data: { id: 'j1', type: 'run_pipeline', payload: {}, lesson_id: 3, cancel_requested: false, ...job } }
  render(
    <MemoryRouter>
      <JobLive jobId="j1" compact={compact} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  state.events = []
  state.status = 'open'
  state.cancel.mockReset()
  state.close.mockReset()
})

describe('JobLive', () => {
  it('mentre carica lo dice', () => {
    state.job = { isPending: true, isError: false, data: undefined }
    render(
      <MemoryRouter>
        <JobLive jobId="j1" />
      </MemoryRouter>,
    )
    expect(screen.getByText('Carico il job…')).toBeInTheDocument()
  })

  it('un job in corso mostra fase, avanzamento ed eventi, e si annulla', () => {
    state.events = [
      { id: 1, type: 'phase_started', payload: { phase: 'review', step: 4, total_steps: 5 }, created_at: '2026-09-20T10:00:00Z' },
      { id: 2, type: 'notice', payload: { message: 'Quota quasi finita', level: 'warning' }, created_at: '2026-09-20T10:00:01Z' },
    ]
    renderJob({ state: 'running', progress: { phase: 'review', current: 8, total: 32, unit_id: '2.1' } })
    expect(screen.getByTestId('phase-progress-title')).toHaveTextContent('Revisione · unità 8 di 32')
    expect(screen.getByRole('progressbar', { name: 'Avanzamento totale' })).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByText('2.1')).toBeInTheDocument()
    const log = screen.getByRole('log', { name: 'Eventi del job' })
    expect(log).toHaveTextContent('Revisione: avviata (4/5)')
    expect(log).toHaveTextContent('Quota quasi finita')
    expect(screen.getByTestId('stream-status')).toHaveTextContent('Eventi dal vivo')
    expect(screen.getByRole('link', { name: /Il rene/ })).toHaveAttribute('href', '/lezioni/3')
    fireEvent.click(screen.getByRole('button', { name: 'Annulla job' }))
    expect(state.cancel).toHaveBeenCalledWith('j1')
  })

  it('in coda aspetta il worker; con annullamento già chiesto non offre di nuovo Annulla', () => {
    renderJob({ state: 'queued', cancel_requested: true })
    expect(screen.getByTestId('phase-progress-title')).toHaveTextContent('In coda · in attesa del worker')
    expect(screen.getByText(/annullamento richiesto/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Annulla job' })).toBeNull()
    expect(screen.getByText('Nessun evento per ora.')).toBeInTheDocument()
  })

  it("in attesa dell'approvazione della scaletta porta alla pagina della scaletta", () => {
    renderJob({ state: 'waiting_for_decision', decision: { kind: 'outline_approval' } })
    expect(screen.getByTestId('job-decision')).toHaveTextContent('devi approvare la scaletta')
    expect(screen.getByRole('link', { name: 'Rivedi la scaletta' })).toHaveAttribute('href', '/lezioni/3/outline')
  })

  it('un job fallito già riprovato mostra errore e nuovo tentativo, senza Riprova né Annulla', () => {
    renderJob({ state: 'failed', error: 'Chiave API non valida', retried_by: 'j2' })
    expect(screen.getByTestId('job-error')).toHaveTextContent('Chiave API non valida')
    expect(screen.getByRole('link', { name: 'Segui il nuovo tentativo' })).toHaveAttribute('href', '/job/j2')
    expect(screen.queryByRole('button', { name: 'Riprova' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Annulla job' })).toBeNull()
  })

  it('un job completato porta alla lezione, tranne nella vista compatta', () => {
    renderJob({ state: 'succeeded' })
    expect(screen.getByRole('link', { name: 'Apri la lezione' })).toHaveAttribute('href', '/lezioni/3')
    cleanup()
    renderJob({ state: 'succeeded' }, true)
    expect(screen.queryByRole('link', { name: 'Apri la lezione' })).toBeNull()
  })

  it('un job fermo sulle issue si chiude (con conferma) senza annullarlo', () => {
    renderJob({ state: 'waiting_for_decision', decision: { kind: 'science_issue' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chiudi e decidi dopo' }))
    expect(screen.getByText(/Le issue restano da valutare nella schermata Revisione/)).toBeInTheDocument()
    expect(state.close).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Chiudi il job' }))
    expect(state.close.mock.calls[0][0]).toBe('j1')
    expect(state.cancel).not.toHaveBeenCalled()
  })

  it('senza una lezione (dati mancanti) il job in attesa si può solo annullare', () => {
    renderJob({ state: 'waiting_for_decision', decision: { kind: 'setup_metadata' }, lesson_id: null })
    expect(screen.queryByRole('button', { name: 'Chiudi e decidi dopo' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Annulla job' })).toBeInTheDocument()
  })

  it('un job chiuso dice dove decidere invece di "Job completato"', () => {
    renderJob({ state: 'succeeded', result: { closed: { kind: 'science_issue', message: 'Chiuso: le issue restano da valutare nella schermata Revisione' } } })
    expect(screen.getByTestId('job-closed')).toHaveTextContent('Chiuso: le issue restano da valutare nella schermata Revisione')
    expect(screen.getByRole('link', { name: 'Apri la revisione' })).toHaveAttribute('href', '/lezioni/3/revisione')
    expect(screen.queryByText(/Job completato/)).toBeNull()
  })
})
