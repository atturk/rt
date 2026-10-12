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

/** Link monouso per aprire una sessione da un altro browser (POST /auth/login-link). */
export function useLoginLink() {
  return useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/auth/login-link')) })
}

/** Indirizzo di RT nella tailnet (nome MagicDNS del Mac), per il QR dell'altro dispositivo. */
export function useTailnet() {
  return useQuery({ queryKey: ['system', 'tailnet'], queryFn: () => unwrap(api.GET('/api/v1/system/tailnet')), staleTime: 60_000 })
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
    // Polling voluto finché non è pronta: la calcola un thread dell'API, non un job (niente eventi live).
    refetchInterval: (query) => (query.state.data && !query.state.data.ready ? 1500 : false),
  })
}

/** Job della lezione, aggiornati dal canale live (liveUpdates.ts) a ogni evento. */
export function useLessonJobs(id: number) {
  return useQuery({
    queryKey: lessonKeys.jobs(id),
    queryFn: () => unwrap(api.GET('/api/v1/jobs', { params: { query: { lesson_id: id, limit: 10 } } })),
  })
}

export function useWorkers() {
  // Polling lento voluto: i worker vivi si vedono dai loro heartbeat, che non sono eventi.
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

export function useUpdateLessonMetadata(id: number) {
  const refresh = useRefreshLesson(id)
  return useMutation({
    mutationFn: (body: Schemas['LessonMetadataUpdate']) =>
      unwrap(api.PATCH('/api/v1/lessons/{lesson_id}/metadata', { params: { path: { lesson_id: id } }, body })),
    onSuccess: () => {
      void refresh()
    },
  })
}

export function usePipelineVersion(id: number) {
  return useQuery({
    queryKey: ['lesson', id, 'pipeline-version'] as const,
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/document/pipeline-version', { params: { path: { lesson_id: id } } })),
    enabled: Number.isFinite(id),
  })
}

export function useRestorePipeline(id: number) {
  const refresh = useRefreshLesson(id)
  return useMutation({
    mutationFn: (leaseToken?: string | null) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/document/restore-pipeline', { params: { path: { lesson_id: id } }, body: { lease_token: leaseToken } })),
    onSuccess: () => {
      void refresh()
    },
  })
}

export function useDeleteLesson(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: id } } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.allLessons })
    },
  })
}

export type PhaseName = 'prepare' | 'outline' | 'rewrite' | 'review' | 'build'

/** Validazione manuale di una fase (Option su "Esegui"): VALID con gli input attuali, senza rieseguirla. */
export function useValidatePhase(id: number) {
  const refresh = useRefreshLesson(id)
  return useMutation({
    mutationFn: (phase: PhaseName) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/phases/{phase}/validate', { params: { path: { lesson_id: id, phase } } })),
    onSettled: () => refresh(),
  })
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
  units: (id: number) => ['lesson', id, 'review-units'] as const,
  issues: (id: number) => ['lesson', id, 'issues'] as const,
  decisions: (id: number) => ['lesson', id, 'decisions'] as const,
}

export function useIssues(id: number, enabled = true) {
  return useQuery({
    queryKey: reviewKeys.issues(id),
    enabled,
    queryFn: () =>
      unwrap(api.GET('/api/v1/lessons/{lesson_id}/issues', { params: { path: { lesson_id: id }, query: { status: 'all' } } })),
  })
}

export function useReviewUnits(id: number) {
  return useQuery({
    queryKey: reviewKeys.units(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/review/units', { params: { path: { lesson_id: id } } })),
  })
}

export function useDecisions(id: number) {
  return useQuery({
    queryKey: reviewKeys.decisions(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/decisions', { params: { path: { lesson_id: id } } })),
  })
}

export type DecisionRequest = Schemas['DecisionRequest']

/** Aggiorna l'issue e i contatori, lasciando intatti gli altri risultati della lezione. */
function setIssueDecision(client: ReturnType<typeof useQueryClient>, id: number, issueId: string, decision: Schemas['Decision'] | null) {
  client.setQueryData<Schemas['IssueList']>(reviewKeys.issues(id), old => {
    if (!old) return old
    const items = old.items.map(item => item.issue.id === issueId ? { ...item, decision, needs_reconfirmation: false } : item)
    const pending = items.filter(item => !item.decision || item.needs_reconfirmation).length
    return { ...old, items, pending, review_complete: pending === 0 }
  })
}

function refreshReview(client: ReturnType<typeof useQueryClient>, id: number) {
  for (const queryKey of [reviewKeys.issues(id), reviewKeys.units(id), lessonKeys.document(id)]) {
    void client.invalidateQueries({ queryKey, exact: true })
  }
}

/** Decisione subito visibile; il server conferma il testo e i tre dati interessati si rileggono. */
export function useDecideIssue(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ issueId, ...body }: { issueId: string } & DecisionRequest) =>
      unwrap(
        api.POST('/api/v1/lessons/{lesson_id}/issues/{issue_id}/decision', {
          params: { path: { lesson_id: id, issue_id: issueId } },
          body,
        }),
      ),
    onMutate: async variables => {
      await Promise.all([reviewKeys.issues(id), reviewKeys.decisions(id)].map(queryKey => client.cancelQueries({ queryKey, exact: true })))
      const previous = client.getQueryData<Schemas['IssueList']>(reviewKeys.issues(id))?.items.find(item => item.issue.id === variables.issueId)
      const previousDecisions = client.getQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id))?.filter(d => d.issue_id === variables.issueId)
      const decision: Schemas['Decision'] = {
        issue_id: variables.issueId, decision: variables.decision, timestamp: new Date().toISOString(), resolved_by: 'api', channel: 'api',
        resolved_text: variables.text ?? (variables.decision === 'accepted' ? previous?.fix_text : previous?.issue.claim as string | undefined),
        anchor: previous?.issue.anchor as Schemas['Anchor'] | undefined,
        notes: variables.notes,
      }
      setIssueDecision(client, id, variables.issueId, decision)
      client.setQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id), old => old ? [...old, decision] : old)
      return { previous, previousDecisions }
    },
    onSuccess: (decision, variables, context) => {
      setIssueDecision(client, id, variables.issueId, decision)
      client.setQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id), old => old ? [...old.filter(d => d.issue_id !== variables.issueId), ...(context?.previousDecisions ?? []), decision] : old)
    },
    onError: (_error, variables, context) => {
      // Ripristina solo questa issue: eventi live e altre decisioni possono essere arrivati nel frattempo.
      if (context?.previous) {
        client.setQueryData<Schemas['IssueList']>(reviewKeys.issues(id), old => {
          if (!old) return old
          const items = old.items.map(item => item.issue.id === variables.issueId ? context.previous! : item)
          const pending = items.filter(item => !item.decision || item.needs_reconfirmation).length
          return { ...old, items, pending, review_complete: pending === 0 }
        })
      }
      client.setQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id), old => old ? [...old.filter(d => d.issue_id !== variables.issueId), ...(context?.previousDecisions ?? [])] : old)
    },
    onSettled: () => refreshReview(client, id),
  })
}

export function useUndoDecision(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (issueId: string) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/decisions/undo', { params: { path: { lesson_id: id } }, body: { issue_id: issueId } })),
    onMutate: async issueId => {
      await Promise.all([reviewKeys.issues(id), reviewKeys.decisions(id)].map(queryKey => client.cancelQueries({ queryKey, exact: true })))
      const previous = client.getQueryData<Schemas['IssueList']>(reviewKeys.issues(id))?.items.find(item => item.issue.id === issueId)
      const decisions = client.getQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id))
      const previousDecisions = decisions?.filter(d => d.issue_id === issueId)
      const earlier = previousDecisions?.slice(0, -1) ?? []
      setIssueDecision(client, id, issueId, earlier.at(-1) ?? null)
      client.setQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id), old => old ? [...old.filter(d => d.issue_id !== issueId), ...earlier] : old)
      return { previous, previousDecisions }
    },
    onError: (_error, issueId, context) => {
      if (context?.previous) {
        client.setQueryData<Schemas['IssueList']>(reviewKeys.issues(id), old => {
          if (!old) return old
          const items = old.items.map(item => item.issue.id === issueId ? context.previous! : item)
          const pending = items.filter(item => !item.decision || item.needs_reconfirmation).length
          return { ...old, items, pending, review_complete: pending === 0 }
        })
      }
      client.setQueryData<Schemas['Decision'][]>(reviewKeys.decisions(id), old => old ? [...old.filter(d => d.issue_id !== issueId), ...(context?.previousDecisions ?? [])] : old)
    },
    onSettled: () => refreshReview(client, id),
  })
}
