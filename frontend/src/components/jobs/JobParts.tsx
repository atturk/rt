import { RotateCcw, TriangleAlert } from 'lucide-react'

import { ApiError, errorMessage } from '@/api/client'
import { useRetryJob, useWorkers } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { JOB_STATE_LABELS, jobStateTone } from '@/lib/jobs'
import { cn } from '@/lib/utils'

export function JobStateBadge({ state }: { state: string }) {
  return (
    <Badge tone={jobStateTone(state)} data-state={state}>
      {JOB_STATE_LABELS[state] ?? state}
    </Badge>
  )
}

/** Barra di avanzamento; value null = indeterminata. */
export function ProgressBar({ value, label, className }: { value: number | null; label: string; className?: string }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div
        className={cn('h-full rounded-full bg-success transition-[width]', value == null && 'w-1/3 animate-pulse')}
        style={value == null ? undefined : { width: `${value}%` }}
      />
    </div>
  )
}

/** Senza worker attivo i job restano in coda: lo si dice subito (GET /workers). */
export function WorkerWarning() {
  const workers = useWorkers()
  if (!workers.data || workers.data.length > 0) return null
  return (
    <Alert tone="warning" data-testid="worker-warning" className="flex items-start gap-2">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>Nessun worker attivo: i job restano in coda finché RT non viene riavviato con la web.</span>
    </Alert>
  )
}

/**
 * "Riprova" per un job fallito (POST /jobs/{id}/retry): crea un job nuovo con lo stesso tipo e
 * payload, che riparte dalla fase fallita (fasi valide saltate, unità già fatte non rifatte).
 * Se la lezione è occupata l'API risponde 409 e lo si dice qui.
 */
export function RetryButton({ jobId, onRetried, size = 'sm' }: { jobId: string; onRetried?: (newJobId: string) => void; size?: 'sm' | 'default' }) {
  const retry = useRetryJob()
  const busy = retry.error instanceof ApiError && retry.error.code === 'lesson_busy'
  return (
    <>
      <Button
        variant="outline"
        size={size}
        disabled={retry.isPending}
        onClick={() => retry.mutate(jobId, { onSuccess: (accepted) => onRetried?.(accepted.job_id) })}
        data-testid="retry-job"
      >
        <RotateCcw aria-hidden />
        {retry.isPending ? 'Riprovo…' : 'Riprova'}
      </Button>
      {retry.isError && (
        <span role="alert" className="basis-full text-xs text-danger">
          {busy ? 'Un altro job sta lavorando su questa lezione: riprova quando ha finito.' : errorMessage(retry.error)}
        </span>
      )}
    </>
  )
}
