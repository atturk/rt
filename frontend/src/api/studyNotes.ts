import { QueryClient, QueryClientContext, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useContext } from 'react'
import { api, unwrap, type Schemas } from './client'

const fallbackClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, gcTime: 0 },
  },
})

// Contratto 4.2.5b2: alla fusione si passa a schema.d.ts
export type StudyNoteWebSource = { title?: string; url?: string }
export type StudyNoteResponse = {
  esito?: string
  spiegazione?: string
  correzione?: string
  sources?: StudyNoteWebSource[]
}
export type StudyNote = Omit<Schemas['StudyNoteView'], 'response' | 'spiegazione_html' | 'correzione_html'> & {
  response?: StudyNoteResponse | null
  /** Le note già in memoria o ricevute da un server precedente restano leggibili. */
  spiegazione_html?: string
  correzione_html?: string
  precedente?: boolean
}
export type StudyNoteCreate = Schemas['StudyNoteCreate']
export type StudyNoteApplyResponse = Schemas['StudyNoteApplyResponse']

export const studyNotesKeys = {
  all: (lessonId: number) => ['study-notes', lessonId] as const,
  unit: (lessonId: number, unitId?: string | null) => ['study-notes', lessonId, unitId ?? 'all'] as const,
  detail: (lessonId: number, noteId: number) => ['study-notes', lessonId, 'note', noteId] as const,
}

export const studyNotesApi = {
  list: (lessonId: number, unitId?: string): Promise<StudyNote[]> =>
    unwrap(
      api.GET('/api/v1/lessons/{lesson_id}/study-notes', {
        params: {
          path: { lesson_id: lessonId },
          query: unitId ? { unit_id: unitId } : {},
        },
      }),
    ) as Promise<StudyNote[]>,

  get: (lessonId: number, noteId: number): Promise<StudyNote> =>
    unwrap(
      api.GET('/api/v1/lessons/{lesson_id}/study-notes/{note_id}', {
        params: { path: { lesson_id: lessonId, note_id: noteId } },
      }),
    ) as Promise<StudyNote>,

  create: (lessonId: number, body: Omit<StudyNoteCreate, 'mock'> & { mock?: boolean }) =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/study-notes', {
        params: { path: { lesson_id: lessonId } },
        body: { mock: false, ...body },
      }),
    ),

  delete: (lessonId: number, noteId: number) =>
    unwrap(
      api.DELETE('/api/v1/lessons/{lesson_id}/study-notes/{note_id}', {
        params: { path: { lesson_id: lessonId, note_id: noteId } },
      }),
    ),

  apply: (lessonId: number, noteId: number): Promise<StudyNoteApplyResponse> =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/study-notes/{note_id}/apply', {
        params: { path: { lesson_id: lessonId, note_id: noteId } },
      }),
    ) as Promise<StudyNoteApplyResponse>,

  undo: (lessonId: number, noteId: number): Promise<StudyNote> =>
    unwrap(
      api.POST('/api/v1/lessons/{lesson_id}/study-notes/{note_id}/undo', {
        params: { path: { lesson_id: lessonId, note_id: noteId } },
      }),
    ) as Promise<StudyNote>,
}

export function useStudyNotes(lessonId: number | null | undefined, unitId?: string) {
  const hasContext = Boolean(useContext(QueryClientContext))
  return useQuery(
    {
      queryKey: lessonId ? studyNotesKeys.unit(lessonId, unitId) : ['study-notes', 'empty'],
      queryFn: () => (lessonId ? studyNotesApi.list(lessonId, unitId) : Promise.resolve([])),
      enabled: Boolean(lessonId && hasContext),
    },
    hasContext ? undefined : fallbackClient,
  )
}

export function useApplyStudyNote(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (noteId: number) => studyNotesApi.apply(lessonId, noteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: studyNotesKeys.all(lessonId) })
      void queryClient.invalidateQueries({ queryKey: ['lesson', lessonId] })
      void queryClient.invalidateQueries({ queryKey: ['study', lessonId] })
      void queryClient.invalidateQueries({ queryKey: ['recall', lessonId] })
    },
  })
}

export function useUndoStudyNote(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (noteId: number) => studyNotesApi.undo(lessonId, noteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: studyNotesKeys.all(lessonId) })
      void queryClient.invalidateQueries({ queryKey: ['lesson', lessonId] })
      void queryClient.invalidateQueries({ queryKey: ['study', lessonId] })
      void queryClient.invalidateQueries({ queryKey: ['recall', lessonId] })
    },
  })
}

export function useDeleteStudyNote(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (noteId: number) => studyNotesApi.delete(lessonId, noteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: studyNotesKeys.all(lessonId) })
    },
  })
}
