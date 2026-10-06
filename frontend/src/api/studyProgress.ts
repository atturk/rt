import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { recallKeys, type StudyLesson } from './recall'

export type StudyStatus = Schemas['StudyStatusUpdate']['status']

export function useStudyStatus(lessonId: number) {
  const client = useQueryClient()
  const key = recallKeys.study(lessonId)
  return useMutation({
    mutationFn: ({ unitId, status }: { unitId: string; status: StudyStatus }) => unwrap(api.PUT(
      '/api/v1/lessons/{lesson_id}/study/units/{unit_id}',
      { params: { path: { lesson_id: lessonId, unit_id: unitId } }, body: { status } },
    )),
    onMutate: async ({ unitId, status }) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<StudyLesson>(key)
      client.setQueryData<StudyLesson>(key, old => old && ({ ...old, units: old.units.map(unit =>
        unit.id === unitId ? { ...unit, status, status_at: new Date().toISOString() } : unit) }))
      return { previous }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSettled: () => Promise.all([
      client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: ['lessons'] }),
    ]),
  })
}

export function useStudyRead(lessonId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (unitId: string) => unwrap(api.POST(
      '/api/v1/lessons/{lesson_id}/study/units/{unit_id}/read',
      { params: { path: { lesson_id: lessonId, unit_id: unitId } } },
    )),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: recallKeys.study(lessonId) }),
      client.invalidateQueries({ queryKey: ['lessons'] }),
    ]),
  })
}
