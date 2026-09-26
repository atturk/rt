import { TriangleAlert } from 'lucide-react'

import { useWorkers } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
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

/** Senza 'rt worker' attivo i job restano in coda: lo si dice subito (GET /workers). */
export function WorkerWarning() {
  const workers = useWorkers()
  if (!workers.data || workers.data.length > 0) return null
  return (
    <Alert tone="warning" data-testid="worker-warning" className="flex items-start gap-2">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>
        Nessun worker attivo: i job restano in coda finché non avvii <code>rt worker</code> (oppure usa{' '}
        <code>rt web</code>, che avvia API e worker insieme).
      </span>
    </Alert>
  )
}
