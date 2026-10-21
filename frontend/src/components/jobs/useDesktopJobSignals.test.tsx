import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type Schemas } from '@/api/client'
import type { UploadItem } from '@/lib/uploadQueue'
import { computeJobsBadgeCount, useDesktopJobSignals } from './useDesktopJobSignals'

type Job = Schemas['Job']

function makeJob(id: string, type: string, state: string, lessonId = 1, lessonTitle = 'La cellula'): Job {
  return {
    id,
    type,
    state: state as Job['state'],
    attempts: 1,
    cancel_requested: false,
    lesson_id: lessonId,
    payload: { lesson_title: lessonTitle },
  }
}

function result(data: unknown, status = 200) {
  return { data, response: new Response('{}', { status }) }
}

describe('useDesktopJobSignals', () => {
  let badgeMock = vi.fn<(count: number) => void>()
  let notificaMock = vi.fn<(titolo: string, testo: string, percorso?: string | null) => void>()

  beforeEach(() => {
    badgeMock = vi.fn<(count: number) => void>()
    notificaMock = vi.fn<(titolo: string, testo: string, percorso?: string | null) => void>()
    window.pywebview = {
      api: {
        salva_copia_backup: vi.fn(),
        badge: badgeMock,
        notifica: notificaMock,
      },
    }
    sessionStorage.setItem('rt-app', '1')
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
    delete (window as unknown as { pywebview?: unknown }).pywebview
  })

  it('nessuna notifica al primo caricamento', async () => {
    const job1 = makeJob('j1', 'run_pipeline', 'running')
    vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result([job1]))) as never)

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderHook(() => useDesktopJobSignals(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })

    await vi.waitFor(() => {
      expect(badgeMock).toHaveBeenCalledWith(1)
    })
    expect(notificaMock).not.toHaveBeenCalled()
  })

  it('notifica su attivo -> succeeded con la finestra non a fuoco', async () => {
    let currentJobs: Job[] = [makeJob('j1', 'run_pipeline', 'running')]
    vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result(currentJobs))) as never)

    // Finestra non a fuoco
    vi.spyOn(document, 'hasFocus').mockReturnValue(false)
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = renderHook(() => useDesktopJobSignals(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })

    await vi.waitFor(() => {
      expect(badgeMock).toHaveBeenCalledWith(1)
    })
    expect(notificaMock).not.toHaveBeenCalled()

    // Seconda lettura: j1 passa a succeeded
    currentJobs = [makeJob('j1', 'run_pipeline', 'succeeded')]
    await client.invalidateQueries()
    rerender()

    await vi.waitFor(() => {
      expect(notificaMock).toHaveBeenCalledTimes(1)
    })
    expect(notificaMock).toHaveBeenCalledWith(
      'Pipeline completa',
      'La cellula: finito',
      '/lezioni/1',
    )
  })

  it('nessuna notifica se la finestra è a fuoco o il tipo è in QUIET_JOB_TYPES', async () => {
    let currentJobs: Job[] = [
      makeJob('j1', 'run_pipeline', 'running'),
      makeJob('j2', 'recall_evaluate', 'running'),
    ]
    vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result(currentJobs))) as never)

    // Finestra a fuoco
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = renderHook(() => useDesktopJobSignals(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })

    await vi.waitFor(() => {
      expect(badgeMock).toHaveBeenCalledWith(2)
    })

    // Transizione con finestra a fuoco: niente notifica per j1
    currentJobs = [
      makeJob('j1', 'run_pipeline', 'succeeded'),
      makeJob('j2', 'recall_evaluate', 'running'),
    ]
    await client.invalidateQueries()
    rerender()
    expect(notificaMock).not.toHaveBeenCalled()

    // Ora finestra non a fuoco, ma transizione su j2 (recall_evaluate: in QUIET_JOB_TYPES)
    vi.spyOn(document, 'hasFocus').mockReturnValue(false)
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    currentJobs = [
      makeJob('j1', 'run_pipeline', 'succeeded'),
      makeJob('j2', 'recall_evaluate', 'succeeded'),
    ]
    await client.invalidateQueries()
    rerender()
    expect(notificaMock).not.toHaveBeenCalled()
  })

  it('badge chiamato con lo stesso conteggio di JobsNavBadge', () => {
    const jobs = [
      makeJob('j1', 'run_pipeline', 'running'),
      makeJob('j2', 'run_phase', 'waiting_for_decision'),
      makeJob('j3', 'run_phase', 'succeeded'),
    ]
    const uploads: UploadItem[] = [
      { id: 'u1', label: '', files: [], loaded: 0, total: null, state: 'uploading', error: null },
      { id: 'u2', label: '', files: [], loaded: 10, total: 10, state: 'failed', error: 'errore' },
    ]
    // 1 attivo + 1 waiting + 1 upload in corso = 3
    expect(computeJobsBadgeCount(jobs, uploads)).toBe(3)
  })
})
