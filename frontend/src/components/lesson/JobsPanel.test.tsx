import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { JobsPanel } from './JobsPanel'

type FakeJob = {
  id: string
  type: string
  state: string
  payload: Record<string, unknown>
  progress?: Record<string, unknown> | null
  cancel_requested?: boolean
  retry_of?: string | null
  retried_by?: string | null
  error?: string | null
}

const state = vi.hoisted(() => ({ jobs: [] as unknown[], cancel: vi.fn(), refresh: vi.fn(), streams: [] as string[] }))

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return {
    ...actual,
    useLessonJobs: () => ({ data: state.jobs }),
    useCancelJob: () => ({ mutate: state.cancel, isError: false }),
    useRefreshLesson: () => state.refresh,
  }
})
vi.mock('@/api/jobs', () => ({ useJobEvents: (jobId: string) => void state.streams.push(jobId) }))
vi.mock('@/components/jobs/JobParts', () => ({ RetryButton: ({ jobId }: { jobId: string }) => <button type="button">Riprova {jobId}</button> }))

const job = (over: Partial<FakeJob> & Pick<FakeJob, 'id' | 'state'>): FakeJob => ({ type: 'run_pipeline', payload: {}, ...over })

function renderPanel(jobs: FakeJob[]) {
  state.jobs = jobs
  const client = new QueryClient()
  const ui = () => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <JobsPanel lessonId={7} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const view = render(ui())
  return {
    rerenderWith(next: FakeJob[]) {
      state.jobs = next
      view.rerender(ui())
    },
  }
}

const item = (id: string) => document.querySelector(`[data-job-id="${id}"]`) as HTMLElement

beforeEach(() => {
  state.cancel.mockReset()
  state.refresh.mockReset()
  state.streams = []
})

describe('JobsPanel', () => {
  it('senza job non mostra nulla', () => {
    renderPanel([])
    expect(screen.queryByTestId('jobs-panel')).toBeNull()
  })

  it('un job in corso mostra fase, unità e avanzamento e si può annullare', () => {
    renderPanel([
      job({
        id: 'j1',
        type: 'run_phase',
        state: 'running',
        payload: { phase: 'review', unit: '2.1' },
        progress: { phase: 'review', current: 8, total: 31, unit_id: '2.1', unit_title: 'Il nefrone' },
      }),
    ])
    const row = item('j1')
    expect(within(row).getByText('Revisione 2.1')).toBeInTheDocument()
    expect(within(row).getByText('in corso')).toBeInTheDocument()
    expect(within(row).getByTestId('job-progress-label')).toHaveTextContent('Revisione · 8/31 · 2.1 Il nefrone')
    expect(within(row).getByLabelText('Avanzamento')).toHaveAttribute('max', '31')
    fireEvent.click(within(row).getByRole('button', { name: 'Annulla' }))
    expect(state.cancel).toHaveBeenCalledWith('j1')
    // Nessuno stream per job: li aggiorna il canale live della pagina (liveUpdates.ts).
    expect(state.streams).toEqual([])
  })

  it('un annullamento già chiesto disabilita il pulsante', () => {
    renderPanel([job({ id: 'j1', state: 'queued', cancel_requested: true })])
    expect(within(item('j1')).getByRole('button', { name: 'Annullamento…' })).toBeDisabled()
  })

  it('un job fallito offre Riprova, o il link al nuovo tentativo se già riprovato', () => {
    renderPanel([
      job({ id: 'f1', state: 'failed', error: 'quota esaurita' }),
      job({ id: 'f2', state: 'failed', retried_by: 'n2' }),
      job({ id: 'n2', state: 'succeeded', retry_of: 'f2' }),
    ])
    expect(within(item('f1')).getByRole('button', { name: 'Riprova f1' })).toBeInTheDocument()
    expect(within(item('f1')).getByText('quota esaurita')).toBeInTheDocument()
    expect(within(item('f2')).queryByRole('button', { name: /Riprova/ })).toBeNull()
    expect(within(item('f2')).getByRole('link', { name: 'Nuovo tentativo' })).toHaveAttribute('href', '/job/n2')
    expect(within(item('n2')).getByText('nuovo tentativo')).toBeInTheDocument()
    expect(state.streams).toEqual([])
  })

  it('mostra solo i 5 job più recenti', () => {
    renderPanel(Array.from({ length: 7 }, (_, i) => job({ id: `j${i}`, state: 'succeeded' })))
    expect(screen.getAllByRole('listitem')).toHaveLength(5)
    expect(item('j5')).toBeNull()
  })

  it('quando un job attivo finisce rilegge la lezione, non prima', () => {
    const view = renderPanel([job({ id: 'j1', state: 'running' })])
    expect(state.refresh).not.toHaveBeenCalled()
    view.rerenderWith([job({ id: 'j1', state: 'running', progress: { current: 2, total: 3 } })])
    expect(state.refresh).not.toHaveBeenCalled()
    view.rerenderWith([job({ id: 'j1', state: 'succeeded' })])
    expect(state.refresh).toHaveBeenCalledTimes(1)
  })
})
