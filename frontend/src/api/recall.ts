import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { formData } from './jobStatus'

export type RecallType = 'quiz' | 'mirata' | 'vasta'
export type RecallQuestion = Schemas['RecallQuestion']
export type RecallAnswerRecord = Schemas['RecallAnswerRecord']
export type Vote = 'up' | 'down' | 'lightning'

export const recallKeys = {
  overview: (id: number) => ['recall', id, 'overview'] as const,
  history: (id: number) => ['recall', id, 'history'] as const,
  units: (id: number) => ['recall', id, 'units'] as const,
  all: (id: number) => ['recall', id] as const,
}

const path = (id: number) => ({ path: { lesson_id: id } })

export function useRecallOverview(id: number) {
  return useQuery({
    queryKey: recallKeys.overview(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall', { params: path(id) })),
  })
}

export function useRecallHistory(id: number, enabled = true) {
  return useQuery({
    queryKey: recallKeys.history(id),
    enabled,
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall/history', { params: path(id) })),
  })
}

/** Dopo ogni scrittura si rilegge pool e storico dall'API. */
function useRecallMutation<TVars, TData>(id: number, fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSettled: () => client.invalidateQueries({ queryKey: recallKeys.all(id) }),
  })
}

export function useGenerateRecall(id: number) {
  return useRecallMutation(id, (qtype: RecallType | null) =>
    unwrap(api.POST('/api/v1/lessons/{lesson_id}/recall/generate', { params: path(id), body: { qtype, mock: false } })),
  )
}

export type RecallUnits = Schemas['RecallUnits']
export type RecallUnit = Schemas['RecallUnit']

/** Unità da cui il recaller genera le domande, con il giudizio del classificatore. */
export function useRecallUnits(id: number) {
  return useQuery({
    queryKey: recallKeys.units(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall/units', { params: path(id) })),
  })
}

/** Salva la selezione (null: solo le rilevanti). La lista si aggiorna subito, senza aspettare l'API. */
export function useSelectRecallUnits(id: number) {
  const client = useQueryClient()
  const key = recallKeys.units(id)
  return useMutation({
    mutationFn: (unitIds: string[] | null) =>
      unwrap(api.PUT('/api/v1/lessons/{lesson_id}/recall/units', { params: path(id), body: { unit_ids: unitIds } })),
    onMutate: async (unitIds) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<RecallUnits>(key)
      if (previous && unitIds) {
        const picked = new Set(unitIds)
        const units = previous.units.map((u) => ({ ...u, selected: picked.has(u.unit_id) }))
        client.setQueryData<RecallUnits>(key, { ...previous, units, custom: true, selected: units.filter((u) => u.selected).length })
      }
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSuccess: (data) => client.setQueryData(key, data),
    onSettled: () => client.invalidateQueries({ queryKey: recallKeys.overview(id) }),
  })
}

export function useNextQuestion(id: number) {
  return useRecallMutation(id, (vars: { qtype: RecallType; excludeId?: string }) =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/recall/next', {
        params: { ...path(id), query: { qtype: vars.qtype, exclude_id: vars.excludeId } },
      }),
    ),
  )
}

/** Quiz: risultato subito. Risposta aperta: job di valutazione (202). */
export function useAnswer(id: number) {
  return useRecallMutation(id, async (vars: { questionId: string; choice?: number; answer?: string }) => {
    const res = await api.POST('/api/v1/lessons/{lesson_id}/recall/answer', {
      params: path(id),
      body: { question_id: vars.questionId, choice: vars.choice ?? null, answer: vars.answer ?? null, mock: false },
    })
    const data = await unwrap(Promise.resolve(res))
    return res.response.status === 202 ? { job: data as unknown as Schemas['JobAccepted'] } : { quiz: data }
  })
}

export function useAnswerVoice(id: number) {
  return useRecallMutation(id, (vars: { questionId: string; audio: Blob }) =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/recall/answer-voice', {
        params: path(id),
        body: { question_id: vars.questionId, audio: '', mock: false },
        bodySerializer: () => formData({ question_id: vars.questionId, audio: vars.audio }),
      }),
    ),
  )
}

export function useVote(id: number) {
  return useRecallMutation(id, (vars: { questionId: string; vote: Vote }) =>
    unwrap(api.POST('/api/v1/lessons/{lesson_id}/recall/vote', { params: path(id), body: { question_id: vars.questionId, vote: vars.vote } })),
  )
}

export function useSkip(id: number) {
  return useRecallMutation(id, (questionId: string) =>
    unwrap(api.POST('/api/v1/lessons/{lesson_id}/recall/skip', { params: path(id), body: { question_id: questionId } })),
  )
}

export type RecallSessionInfo = Schemas['RecallSessionInfo']
export type RecallSessionState = Schemas['RecallSessionState']
export type TelegramRecallStatus = Schemas['TelegramRecallStatus']

export const sessionKeys = {
  lesson: (id: number) => ['recall', id, 'session'] as const,
  telegram: ['recall-telegram'] as const,
}

/** Sessione qui e su Telegram. Mentre il bot esegue una richiesta si rilegge spesso. */
export function useRecallSession(id: number) {
  return useQuery({
    queryKey: sessionKeys.lesson(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall/session', { params: path(id) })),
    refetchInterval: (query) => {
      const state = query.state.data?.command?.state
      return state === 'pending' || state === 'running' ? 1_000 : 10_000
    },
  })
}

/** Bot pronto per il recall e sessioni in corso su Telegram (tutte le lezioni). */
export function useTelegramRecall() {
  return useQuery({
    queryKey: sessionKeys.telegram,
    queryFn: () => unwrap(api.GET('/api/v1/recall/telegram')),
    refetchInterval: 10_000,
  })
}

function useSessionMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSettled: () =>
      Promise.all([client.invalidateQueries({ queryKey: ['recall'] }), client.invalidateQueries({ queryKey: sessionKeys.telegram })]),
  })
}

export function useEndSession(id: number) {
  return useSessionMutation(() => unwrap(api.POST('/api/v1/lessons/{lesson_id}/recall/session/end', { params: path(id) })))
}

export function useStartTelegram(id: number) {
  return useSessionMutation((qtype: RecallType) =>
    unwrap(api.POST('/api/v1/lessons/{lesson_id}/recall/telegram/start', { params: path(id), body: { qtype, mock: false } })),
  )
}

export function useStopTelegram() {
  return useSessionMutation((sessionId: number) =>
    unwrap(api.POST('/api/v1/recall/telegram/sessions/{session_id}/stop', { params: { path: { session_id: sessionId } } })),
  )
}

// ---------------------------------------------------------------- recall per materia

export type SubjectRecall = Schemas['SubjectRecall']
export type LessonRecallStats = Schemas['LessonRecallStats']
export type SubjectQuestion = Schemas['SubjectQuestion']

export const subjectKeys = {
  all: ['recall-subject'] as const,
  list: ['recall-subject', 'list'] as const,
  one: (materia: string) => ['recall-subject', 'one', materia] as const,
}

/** Pool di ogni lezione, per materia, e sessioni per materia in corso. */
export function useSubjectsRecall() {
  return useQuery({ queryKey: subjectKeys.list, queryFn: () => unwrap(api.GET('/api/v1/recall/subjects')) })
}

export function useSubjectRecall(materia: string) {
  return useQuery({
    queryKey: subjectKeys.one(materia),
    queryFn: () => unwrap(api.GET('/api/v1/recall/subject', { params: { query: { materia } } })),
  })
}

/** Dopo ogni scrittura si rileggono pool e sessioni della materia (e quelle delle lezioni). */
function useSubjectMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: subjectKeys.all }), client.invalidateQueries({ queryKey: ['recall'] })]),
  })
}

export function useSubjectNext(materia: string) {
  return useSubjectMutation((vars: { qtype: RecallType; exclude?: string }) =>
    unwrap(api.POST('/api/v1/recall/subject/next', { params: { query: { materia, qtype: vars.qtype, exclude: vars.exclude } } })),
  )
}

export function useSubjectEnd(materia: string) {
  return useSubjectMutation(() => unwrap(api.POST('/api/v1/recall/subject/end', { params: { query: { materia } } })))
}

export function useSubjectGenerate(materia: string) {
  return useSubjectMutation(() => unwrap(api.POST('/api/v1/recall/subject/generate', { params: { query: { materia } } })))
}
