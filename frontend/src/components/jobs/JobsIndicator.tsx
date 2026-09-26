import { Activity } from 'lucide-react'
import { Link } from 'react-router'

import { useJobs, useWorkers } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { decisionLabel, decisionLink, isActive } from '@/lib/jobs'
import { cn } from '@/lib/utils'

/** Pannello globale nell'intestazione: job attivi e decisioni in attesa, da ogni pagina. */
export function JobsIndicator() {
  const jobs = useJobs({ limit: 50 }, { poll: 5_000 })
  const workers = useWorkers()
  const active = (jobs.data ?? []).filter((j) => isActive(j.state)).length
  const waiting = (jobs.data ?? []).filter((j) => j.state === 'waiting_for_decision').length
  const noWorker = workers.data?.length === 0 && active > 0
  const label = [
    active ? `${active} job attivi` : 'Nessun job attivo',
    waiting ? `${waiting} in attesa di una tua decisione` : '',
    noWorker ? 'nessun worker attivo' : '',
  ]
    .filter(Boolean)
    .join(', ')
  return (
    <Link
      to="/job"
      aria-label={`Job: ${label}`}
      title={label}
      data-testid="jobs-indicator"
      className={cn(
        'relative inline-flex size-9 items-center justify-center rounded-md border border-input bg-card hover:bg-muted',
        (waiting > 0 || noWorker) && 'border-warning text-warning',
      )}
    >
      <Activity className={cn('size-4', active > 0 && 'animate-pulse')} aria-hidden />
      {active + waiting > 0 && (
        <span className="absolute -right-1.5 -top-1.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-bold leading-4 text-primary-foreground">
          {active + waiting}
        </span>
      )}
    </Link>
  )
}

/** Nella pagina lezione: pipeline in attesa ("serve la tua approvazione") o job in corso. */
export function LessonJobBanner({ lessonId }: { lessonId: number }) {
  const jobs = useJobs({ lesson_id: lessonId, limit: 20 }, { poll: 5_000 })
  const waiting = (jobs.data ?? []).find((j) => j.state === 'waiting_for_decision')
  const running = (jobs.data ?? []).find((j) => isActive(j.state))
  return (
    <div className="flex flex-col gap-2" data-testid="lesson-jobs">
      {waiting && (
        <Alert tone="warning" data-testid="lesson-waiting">
          <strong>Serve la tua approvazione:</strong> la pipeline è ferma finché non decidi (devi {decisionLabel(waiting.decision)}).{' '}
          <Link to={decisionLink(waiting) ?? `/job/${waiting.id}`} className="font-semibold underline">
            {waiting.decision?.kind === 'outline_approval' ? 'Rivedi la scaletta' : 'Vai alla decisione'}
          </Link>
        </Alert>
      )}
      {running && (
        <Alert>
          Job in corso sulla lezione.{' '}
          <Link to={`/job/${running.id}`} className="font-semibold underline">
            Segui l'avanzamento
          </Link>
        </Alert>
      )}
      <p className="flex gap-4 text-xs">
        <Link to={`/lezioni/${lessonId}/outline`} className="underline">
          Scaletta e approvazione
        </Link>
        <Link to={`/job?lezione=${lessonId}`} className="underline">
          Job della lezione
        </Link>
      </p>
    </div>
  )
}
