import { useEffect, useRef } from 'react'

import { errorMessage } from '@/api/client'
import { useWorkers } from '@/api/hooks'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { Alert } from '@/components/ui/alert'

const STATE_TEXT: Record<string, string> = {
  queued: 'In coda',
  running: 'In corso',
  waiting_for_decision: 'In attesa di una decisione',
  succeeded: 'Completato',
  failed: 'Fallito',
  cancelled: 'Annullato',
}

/** Avanzamento di un job letto dall'API (GET /jobs/{id}); avvisa se nessun worker è attivo. */
export function JobProgress({
  jobId,
  label,
  onFinished,
}: {
  jobId: string
  label: string
  /** Chiamata una volta quando il job finisce: di solito invalida le query toccate dal job. */
  onFinished?: (state: string) => void
}) {
  const job = useJobStatus(jobId)
  const workers = useWorkers()
  const notified = useRef<string | null>(null)
  const finalState = jobFinished(job.data) ? job.data!.state : null
  useEffect(() => {
    if (finalState && notified.current !== jobId) {
      notified.current = jobId
      onFinished?.(finalState)
    }
  }, [finalState, jobId, onFinished])
  if (job.isError) return <Alert tone="danger">{errorMessage(job.error)}</Alert>
  const data = job.data
  const state = data?.state ?? 'queued'
  const progress = data?.progress as { phase?: string; message?: string; current?: number; total?: number } | null | undefined
  const percent = progress?.total ? Math.round(((progress.current ?? 0) / progress.total) * 100) : null
  const tone = state === 'failed' ? 'danger' : state === 'succeeded' ? 'neutral' : 'warning'
  return (
    <div className="flex flex-col gap-2" data-testid="job-progress" data-state={state}>
      <Alert tone={tone}>
        <span className="font-medium">{label}:</span> {STATE_TEXT[state] ?? state}
        {progress?.message && !jobFinished(data) ? ` · ${progress.message}` : ''}
        {data?.error ? ` · ${data.error}` : ''}
      </Alert>
      {!jobFinished(data) && (
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? undefined}
          className="h-1.5 overflow-hidden rounded-full bg-muted"
        >
          <div className={percent === null ? 'h-full w-1/3 animate-pulse bg-success' : 'h-full bg-success'} style={percent === null ? undefined : { width: `${percent}%` }} />
        </div>
      )}
      {state === 'queued' && workers.data?.length === 0 && (
        <Alert tone="warning">Nessun worker attivo: il job parte quando avvii RT con <code>rt web</code> o <code>rt worker</code>.</Alert>
      )}
    </div>
  )
}
