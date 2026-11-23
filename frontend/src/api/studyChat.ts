import { QueryClient, QueryClientContext, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useContext } from 'react'

import { api, CSRF_COOKIE, CSRF_HEADER, readCookie, toApiError, unwrap, type Schemas } from './client'
import { studyNotesKeys } from './studyNotes'

const fallbackClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, gcTime: 0 },
  },
})

export type StudyChatMessage = Schemas['StudyChatMessageView']
export type StudyChatSendResponse = Schemas['StudyChatSendResponse']
export type StudyChatSaveResponse = Schemas['StudyChatSaveResponse']

export const studyChatKeys = {
  lesson: (lessonId: number) => ['study-chat', lessonId] as const,
}

function csrfHeaders(): Record<string, string> {
  const csrf = readCookie(CSRF_COOKIE)
  return csrf ? { [CSRF_HEADER]: csrf } : {}
}

export const studyChatApi = {
  list: (lessonId: number): Promise<StudyChatMessage[]> =>
    unwrap(
      api.GET('/api/v1/lessons/{lesson_id}/chat', {
        params: { path: { lesson_id: lessonId } },
      }),
    ) as Promise<StudyChatMessage[]>,

  send: async (
    lessonId: number,
    payload: { text: string; unitId?: string; images?: File[]; mock?: boolean },
  ): Promise<StudyChatSendResponse> => {
    const form = new FormData()
    form.append('text', payload.text)
    form.append('unit_id', payload.unitId ?? '')
    form.append('mock', payload.mock ? 'true' : 'false')
    for (const file of payload.images ?? []) {
      form.append('images', file)
    }
    let response: Response
    try {
      response = await fetch(`/api/v1/lessons/${lessonId}/chat`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
        body: form,
      })
    } catch {
      throw toApiError(0, undefined)
    }
    let body: unknown = undefined
    try {
      body = await response.json()
    } catch {
      // ignore non-json
    }
    if (!response.ok) throw toApiError(response.status, body)
    return body as StudyChatSendResponse
  },

  clear: (lessonId: number) =>
    unwrap(
      api.DELETE('/api/v1/lessons/{lesson_id}/chat', {
        params: { path: { lesson_id: lessonId } },
      }),
    ),

  saveNote: (lessonId: number, messageId: number): Promise<StudyChatSaveResponse> =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/chat/{message_id}/save', {
        params: { path: { lesson_id: lessonId, message_id: messageId } },
      }),
    ) as Promise<StudyChatSaveResponse>,

  unsaveNote: (lessonId: number, messageId: number): Promise<StudyChatMessage> =>
    unwrap(
      api.DELETE('/api/v1/lessons/{lesson_id}/chat/{message_id}/save', {
        params: { path: { lesson_id: lessonId, message_id: messageId } },
      }),
    ) as Promise<StudyChatMessage>,

  transcribe: async (lessonId: number, audio: File): Promise<{ text: string }> => {
    const form = new FormData()
    form.append('audio', audio)
    let response: Response
    try {
      response = await fetch(`/api/v1/lessons/${lessonId}/chat/transcribe`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
        body: form,
      })
    } catch {
      throw toApiError(0, undefined)
    }
    let body: unknown = undefined
    try {
      body = await response.json()
    } catch {
      // ignore
    }
    if (!response.ok) throw toApiError(response.status, body)
    return body as { text: string }
  },
}

export function useStudyChat(lessonId: number | null | undefined, enabled = true) {
  const hasContext = Boolean(useContext(QueryClientContext))
  return useQuery(
    {
      queryKey: lessonId ? studyChatKeys.lesson(lessonId) : ['study-chat', 'empty'],
      queryFn: () => (lessonId ? studyChatApi.list(lessonId) : Promise.resolve([])),
      enabled: Boolean(lessonId && enabled && hasContext),
    },
    hasContext ? undefined : fallbackClient,
  )
}

export function useSendStudyChat(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { text: string; unitId?: string; images?: File[]; mock?: boolean }) =>
      studyChatApi.send(lessonId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData<StudyChatMessage[]>(studyChatKeys.lesson(lessonId), (old) => {
        const list = old ? [...old] : []
        if (!list.some((m) => m.id === data.user_message.id)) list.push(data.user_message)
        if (!list.some((m) => m.id === data.assistant_message.id)) list.push(data.assistant_message)
        return list
      })
    },
  })
}

export function useClearStudyChat(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => studyChatApi.clear(lessonId),
    onSuccess: () => {
      queryClient.setQueryData<StudyChatMessage[]>(studyChatKeys.lesson(lessonId), [])
    },
  })
}

export function useSaveStudyChatNote(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (messageId: number) => studyChatApi.saveNote(lessonId, messageId),
    onSuccess: (data) => {
      queryClient.setQueryData<StudyChatMessage[]>(studyChatKeys.lesson(lessonId), (old) =>
        old ? old.map((m) => (m.id === data.message.id ? data.message : m)) : old,
      )
      void queryClient.invalidateQueries({ queryKey: studyNotesKeys.all(lessonId) })
    },
  })
}

export function useUnsaveStudyChatNote(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (messageId: number) => studyChatApi.unsaveNote(lessonId, messageId),
    onSuccess: (updated) => {
      queryClient.setQueryData<StudyChatMessage[]>(studyChatKeys.lesson(lessonId), (old) =>
        old ? old.map((m) => (m.id === updated.id ? updated : m)) : old,
      )
      void queryClient.invalidateQueries({ queryKey: studyNotesKeys.all(lessonId) })
    },
  })
}

export function useTranscribeStudyChatAudio(lessonId: number) {
  return useMutation({
    mutationFn: (audio: File) => studyChatApi.transcribe(lessonId, audio),
  })
}
