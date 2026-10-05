import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { jobKeys } from './jobs'

/** Export multiplo con avanzamento; lo ZIP resta riscaricabile dopo la conclusione. */
export function useExportLessons() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['LessonExportRequest']) => unwrap(api.POST('/api/v1/lesson-exports', { body })),
    onSuccess: () => { void client.invalidateQueries({ queryKey: jobKeys.all }) },
  })
}

export function lessonExportUrl(jobId: string): string {
  return `/api/v1/lesson-exports/${encodeURIComponent(jobId)}/file`
}
