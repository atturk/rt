import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'

export const queryKeys = {
  me: ['auth', 'me'] as const,
  health: ['health'] as const,
  lessons: (filters: LessonFilters) => ['lessons', filters] as const,
  allLessons: ['lessons'] as const,
  lesson: (id: number) => ['lesson', id, 'detail'] as const,
  costs: ['costs'] as const,
}

export type LessonFilters = { materia?: string; state?: string; q?: string }

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => unwrap(api.GET('/api/v1/auth/me')),
    retry: false,
    staleTime: 60_000,
  })
}

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: () => unwrap(api.GET('/api/v1/health')), staleTime: 60_000 })
}

export function useLessons(filters: LessonFilters = {}) {
  const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as LessonFilters
  return useQuery({
    queryKey: queryKeys.lessons(query),
    queryFn: () => unwrap(api.GET('/api/v1/lessons', { params: { query } })),
  })
}

export function useLesson(id: number) {
  return useQuery({
    queryKey: queryKeys.lesson(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: id } } })),
    enabled: Number.isFinite(id),
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => unwrap(api.POST('/api/v1/auth/session', { body: { token } })),
    onSuccess: () => client.invalidateQueries(),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/auth/session')),
    onSettled: () => client.clear(),
  })
}

// ---------------------------------------------------------------- vista lezione (RT4-F2)

export const lessonKeys = {
  all: (id: number) => ['lesson', id] as const,
  document: (id: number) => ['lesson', id, 'document'] as const,
  phases: (id: number) => ['lesson', id, 'phases'] as const,
  waveform: (id: number) => ['lesson', id, 'waveform'] as const,
  jobs: (id: number) => ['lesson', id, 'jobs'] as const,
}

const ACTIVE_JOB_STATES = new Set(['queued', 'running'])
export const isActiveJob = (state: string) => ACTIVE_JOB_STATES.has(state)

export function useLessonDocument(id: number) {
  return useQuery({
    queryKey: lessonKeys.document(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/document', { params: { path: { lesson_id: id } } })),
  })
}

export function usePhases(id: number) {
  return useQuery({
    queryKey: lessonKeys.phases(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/phases', { params: { path: { lesson_id: id } } })),
  })
}

export function useWaveform(id: number, enabled: boolean) {
  return useQuery({
    queryKey: lessonKeys.waveform(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/audio/waveform', { params: { path: { lesson_id: id } } })),
    enabled,
    staleTime: Infinity,
    refetchInterval: (query) => (query.state.data && !query.state.data.ready ? 1500 : false),
  })
}

/** Job della lezione, riletti ogni 1,5 s finché uno è in coda o in esecuzione. */
export function useLessonJobs(id: number) {
  return useQuery({
    queryKey: lessonKeys.jobs(id),
    queryFn: () => unwrap(api.GET('/api/v1/jobs', { params: { query: { lesson_id: id, limit: 10 } } })),
    refetchInterval: (query) => (query.state.data?.some((j) => isActiveJob(j.state)) ? 1500 : false),
  })
}

export function useWorkers() {
  return useQuery({ queryKey: ['workers'], queryFn: () => unwrap(api.GET('/api/v1/workers')), refetchInterval: 10_000 })
}

/** Dopo un job o una scrittura sulla lezione: rilegge tutto quello che la riguarda. */
export function useRefreshLesson(id: number) {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: lessonKeys.all(id) }),
      client.invalidateQueries({ queryKey: queryKeys.allLessons }),
      client.invalidateQueries({ queryKey: queryKeys.costs }),
    ])
}

export type JobRequest = Schemas['JobRequest']

export function useRunJob(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<JobRequest> & Pick<JobRequest, 'type'>) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/jobs', { params: { path: { lesson_id: id } }, body: body as JobRequest })),
    onSettled: () => client.invalidateQueries({ queryKey: lessonKeys.jobs(id) }),
  })
}

export function useCancelJob(lessonId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => unwrap(api.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } })),
    onSettled: () => client.invalidateQueries({ queryKey: lessonKeys.jobs(lessonId) }),
  })
}

// ---------------------------------------------------------------- review contestuale (RT4-F3)

export const reviewKeys = {
  issues: (id: number) => ['lesson', id, 'issues'] as const,
  decisions: (id: number) => ['lesson', id, 'decisions'] as const,
}

export function useIssues(id: number) {
  return useQuery({
    queryKey: reviewKeys.issues(id),
    queryFn: () =>
      unwrap(api.GET('/api/v1/lessons/{lesson_id}/issues', { params: { path: { lesson_id: id }, query: { status: 'all' } } })),
  })
}

export function useDecisions(id: number) {
  return useQuery({
    queryKey: reviewKeys.decisions(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/decisions', { params: { path: { lesson_id: id } } })),
  })
}

export type DecisionRequest = Schemas['DecisionRequest']

/** Decisione su un'issue: dopo la scrittura rilegge issue, ledger, documento, fasi e job. */
export function useDecideIssue(id: number) {
  const refresh = useRefreshLesson(id)
  return useMutation({
    mutationFn: ({ issueId, ...body }: { issueId: string } & DecisionRequest) =>
      unwrap(
        api.POST('/api/v1/lessons/{lesson_id}/issues/{issue_id}/decision', {
          params: { path: { lesson_id: id, issue_id: issueId } },
          body,
        }),
      ),
    onSettled: () => {
      void refresh()
    },
  })
}

export function useUndoDecision(id: number) {
  const refresh = useRefreshLesson(id)
  return useMutation({
    mutationFn: (issueId: string) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/decisions/undo', { params: { path: { lesson_id: id } }, body: { issue_id: issueId } })),
    onSettled: () => {
      void refresh()
    },
  })
}
