import { Link } from 'react-router'

import { useJobs, useWorkers } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { decisionLabel, decisionLink, isActive } from '@/lib/jobs'
import { cn } from '@/lib/utils'

/**
 * Badge sulla voce "Job" del menu: numero di job attivi e decisioni in attesa, da ogni pagina.
 * Il testo per i lettori di schermo completa il nome del link ("Job: 2 job attivi, ...").
 */
export function JobsNavBadge() {
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
  const count = active + waiting
  return (
    <span data-testid="jobs-indicator" data-active={active} data-waiting={waiting} title={label} className="inline-flex">
      <span className="sr-only">: {label}</span>
      {(count > 0 || noWorker) && (
        <span
          aria-hidden
          className={cn(
            'min-w-4 rounded-full px-1 text-center text-[10px] font-bold leading-4',
            waiting > 0 || noWorker ? 'bg-warning text-background' : 'bg-primary text-primary-foreground',
          )}
        >
          {noWorker && count === 0 ? '!' : count}
        </span>
      )}
    </span>
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
