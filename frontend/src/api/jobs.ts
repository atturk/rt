/**
 * Hook di job, importazione e outline (RT4-F4). Lo stato dei job si rilegge sempre dall'API:
 * lo stream SSE serve a mostrare gli eventi dal vivo e a dire quando rileggere.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { api, unwrap, type Schemas } from './client'
import { queryKeys } from './hooks'
import type { paths } from './schema'
import { xhrFetch, type UploadProgress } from './upload'
import { isActive, mergeEvents, type JobEvent } from '@/lib/jobs'

export type JobFilters = { state?: string; lesson_id?: number; limit?: number }

export const jobKeys = {
  all: ['jobs'] as const,
  list: (filters: JobFilters) => ['jobs', 'list', filters] as const,
  job: (id: string) => ['jobs', 'job', id] as const,
  workers: ['workers'] as const,
  outline: (lessonId: number) => ['outline', lessonId] as const,
}

/** Dopo un job o una decisione cambiano lezioni, fasi, outline e job: si rilegge tutto. */
export function invalidateAfterJob(client: QueryClient, lessonId?: number | null) {
  void client.invalidateQueries({ queryKey: jobKeys.all })
  void client.invalidateQueries({ queryKey: queryKeys.allLessons })
  if (lessonId != null) {
    void client.invalidateQueries({ queryKey: queryKeys.lesson(lessonId) })
    void client.invalidateQueries({ queryKey: jobKeys.outline(lessonId) })
  }
}

export function useJobs(filters: JobFilters = {}, options: { poll?: number } = {}) {
  const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && v !== '')) as JobFilters
  return useQuery({
    queryKey: jobKeys.list(query),
    queryFn: () => unwrap(api.GET('/api/v1/jobs', { params: { query } })),
    refetchInterval: options.poll ?? false,
  })
}

export function useJob(id: string) {
  return useQuery({
    queryKey: jobKeys.job(id),
    queryFn: () => unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id } } })),
    enabled: !!id,
  })
}

export function useWorkers() {
  return useQuery({
    queryKey: jobKeys.workers,
    queryFn: () => unwrap(api.GET('/api/v1/workers')),
    refetchInterval: 15_000,
  })
}

export function useCancelJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: id } } })),
    onSettled: (job) => invalidateAfterJob(client, job?.lesson_id),
  })
}

export type NewLesson = {
  files: File[]
  date: string
  materia: string
  argomenti: string
  run: boolean
  mock: boolean
  auto_accept: boolean
}

/** POST /lessons multipart con avanzamento dell'upload. */
export function useCreateLesson() {
  const client = useQueryClient()
  const [progress, setProgress] = useState<UploadProgress | null>(null)
  const mutation = useMutation({
    mutationFn: (input: NewLesson) => {
      const form = new FormData()
      for (const file of input.files) form.append('audio', file, file.name)
      form.append('date', input.date)
      form.append('materia', input.materia)
      form.append('argomenti', input.argomenti)
      form.append('run', String(input.run))
      form.append('mock', String(input.mock))
      form.append('auto_accept', String(input.auto_accept))
      setProgress({ loaded: 0, total: input.files.reduce((sum, f) => sum + f.size, 0) })
      const body = {
        audio: input.files.map((f) => f.name),
        date: input.date,
        materia: input.materia,
        argomenti: input.argomenti,
        run: input.run,
        mock: input.mock,
        auto_accept: input.auto_accept,
        with_review: true,
      } satisfies Schemas['Body_create_lesson_api_v1_lessons_post']
      return unwrap(api.POST('/api/v1/lessons', { body, bodySerializer: () => form, fetch: xhrFetch(form, setProgress) }))
    },
    onSettled: () => invalidateAfterJob(client),
  })
  return { ...mutation, progress: mutation.isPending ? progress : null }
}

// ---------------------------------------------------------------- outline

export function useOutline(lessonId: number) {
  return useQuery({
    queryKey: jobKeys.outline(lessonId),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/outline', { params: { path: { lesson_id: lessonId } } })),
    enabled: Number.isFinite(lessonId),
    retry: false,
  })
}

export function useApproveOutline(lessonId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/lessons/{lesson_id}/outline/approve', { params: { path: { lesson_id: lessonId } } })),
    onSettled: () => invalidateAfterJob(client, lessonId),
  })
}

export function useReviseOutline(lessonId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['OutlineRevision']) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/outline/revise', { params: { path: { lesson_id: lessonId } }, body })),
    onSettled: () => invalidateAfterJob(client, lessonId),
  })
}

// ---------------------------------------------------------------- eventi live (SSE)

const EVENTS_PATH = '/api/v1/jobs/{job_id}/events' satisfies keyof paths

export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'ended' | 'error'

/**
 * Eventi del job da GET /jobs/{id}/events (EventSource). Il browser si riconnette da solo
 * dopo una disconnessione mandando Last-Event-ID, così lo stream riprende dall'ultimo evento
 * ricevuto. Il server chiude lo stream ('end') quando il job finisce o aspetta una decisione;
 * se poi il job riparte (decisione presa) lo stream si riapre dall'ultimo id.
 * Ogni evento fa rileggere il job dall'API, la fine anche lezioni e outline.
 */
export function useJobEvents(jobId: string, job?: Pick<Schemas['Job'], 'state' | 'lesson_id'>, dataUpdatedAt = 0) {
  const client = useQueryClient()
  const [events, setEvents] = useState<JobEvent[]>([])
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [endedAt, setEndedAt] = useState(0)
  const lastId = useRef(0)
  const lessonId = useRef(job?.lesson_id)
  useEffect(() => {
    lessonId.current = job?.lesson_id
  }, [job?.lesson_id])

  // riaperto solo se, dopo la fine, l'API dice che il job è di nuovo attivo
  const shouldStream = !!jobId && (endedAt === 0 || (dataUpdatedAt > endedAt && isActive(job?.state)))

  useEffect(() => {
    if (!shouldStream) return
    let refresh: ReturnType<typeof setTimeout> | undefined
    const refetchJob = () => {
      clearTimeout(refresh)
      refresh = setTimeout(() => void client.invalidateQueries({ queryKey: jobKeys.job(jobId) }), 300)
    }
    const url = `${EVENTS_PATH.replace('{job_id}', encodeURIComponent(jobId))}?after=${lastId.current}`
    const source = new EventSource(url, { withCredentials: true })
    source.onopen = () => {
      setEndedAt(0)
      setStatus('open')
    }
    source.onerror = () => setStatus(source.readyState === EventSource.CLOSED ? 'error' : 'reconnecting')
    source.onmessage = () => undefined
    const onEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as JobEvent
      lastId.current = Math.max(lastId.current, event.id)
      setEvents((current) => mergeEvents(current, [event]))
      setStatus('open')
      refetchJob()
    }
    const types = [
      'job_queued', 'job_started', 'job_requeued', 'job_resumed', 'job_cancel_requested', 'job_waiting', 'job_finished',
      'phase_started', 'phase_progress', 'phase_completed', 'phase_failed', 'cost_updated', 'decision_required', 'notice',
    ]
    for (const type of types) source.addEventListener(type, onEvent)
    source.addEventListener('end', () => {
      source.close()
      setStatus('ended')
      setEndedAt(Date.now())
      clearTimeout(refresh)
      void client.invalidateQueries({ queryKey: jobKeys.job(jobId) })
      invalidateAfterJob(client, lessonId.current)
    })
    return () => {
      clearTimeout(refresh)
      source.close()
    }
  }, [client, jobId, shouldStream])

  return { events, status }
}
