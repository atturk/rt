import { useQuery } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'

export type Job = Schemas['Job']
export type JobAccepted = Schemas['JobAccepted']

const FINISHED = new Set(['succeeded', 'failed', 'cancelled'])

export function jobFinished(job: Pick<Job, 'state'> | undefined): boolean {
  return !!job && FINISHED.has(job.state)
}

/** Stato di un job letto dall'API, ripetuto finché non finisce (o si ferma su una decisione). */
export function useJobStatus(jobId: string | null | undefined) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: () => unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: jobId! } } })),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const job = query.state.data
      return job && (jobFinished(job) || job.state === 'waiting_for_decision') ? false : 1000
    },
  })
}

/** Corpo multipart per gli endpoint con upload: openapi-fetch passa il FormData così com'è. */
export function formData(fields: Record<string, string | number | boolean | Blob | (string | Blob)[] | null | undefined>): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value === null || value === undefined) continue
    if (Array.isArray(value)) value.forEach((v) => form.append(key, v))
    else if (value instanceof Blob) form.append(key, value, value instanceof File ? value.name : 'blob')
    else form.append(key, String(value))
  }
  return form
}
