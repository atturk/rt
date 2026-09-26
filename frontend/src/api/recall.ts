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
  all: (id: number) => ['recall', id] as const,
}

const path = (id: number) => ({ path: { lesson_id: id } })

export function useRecallOverview(id: number) {
  return useQuery({
    queryKey: recallKeys.overview(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall', { params: path(id) })),
  })
}

export function useRecallHistory(id: number) {
  return useQuery({
    queryKey: recallKeys.history(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/recall/history', { params: path(id) })),
  })
}

/** Dopo ogni scrittura si rilegge riserva e storico dall'API. */
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
