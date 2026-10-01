import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { api, unwrap } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'

/** Classificazioni della lezione (GET /lessons/{id}/relevance), condivise con la pagina Classificatore. */
export function useRelevance(lessonId: number) {
  return useQuery({
    queryKey: ['relevance', lessonId],
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/relevance', { params: { path: { lesson_id: lessonId } } })),
  })
}

/** Avvia il classificatore sulla lezione (job unit_relevance, come 'rt relevance') e segue il job. */
export function useRunClassifier(lessonId: number) {
  const client = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: (force: boolean) => unwrap(api.POST('/api/v1/lessons/{lesson_id}/relevance/run', {
      params: { path: { lesson_id: lessonId } }, body: { force, mock: false },
    })),
    onMutate: () => setJobId(null),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  })
  const finished = useCallback(() => {
    void client.invalidateQueries({ queryKey: ['relevance', lessonId] })
    void client.invalidateQueries({ queryKey: ['lesson', lessonId] })
    void client.invalidateQueries({ queryKey: ['recall'] })
    void client.invalidateQueries({ queryKey: ['recall-subject'] })
  }, [client, lessonId])
  const job = useJobStatus(jobId)
  const busy = start.isPending || (!!jobId && !job.isError && !jobFinished(job.data))
  return { start, jobId, busy, finished }
}
