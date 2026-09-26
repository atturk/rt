import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { useCancelJob, useJob, useJobEvents, type StreamStatus } from '@/api/jobs'
import { JobStateBadge, ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { lessonTitle } from '@/lib/format'
import { decisionLabel, decisionLink, describeEvent, isActive, isTerminal, jobTypeLabel, progressPercent } from '@/lib/jobs'
import { cn } from '@/lib/utils'

const STREAM_LABELS: Record<StreamStatus, string> = {
  connecting: 'Collegamento agli eventi…',
  open: 'Eventi dal vivo',
  reconnecting: 'Connessione persa: riprendo dall\'ultimo evento…',
  ended: 'Stream chiuso',
  error: 'Eventi non disponibili',
}

const TONE_CLASSES = { neutral: '', success: 'text-success', warning: 'text-warning', danger: 'text-danger' }

function formatTime(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Dettaglio di un job con eventi live (SSE), avanzamento, decisione attesa e annullamento. */
export function JobLive({ jobId, compact = false }: { jobId: string; compact?: boolean }) {
  const job = useJob(jobId)
  const { events, status } = useJobEvents(jobId, job.data, job.dataUpdatedAt)
  const cancel = useCancelJob()
  const lessons = useLessons()

  if (job.isPending) return <p className="text-sm text-muted-foreground">Carico il job…</p>
  if (job.isError) return <Alert tone="danger">{errorMessage(job.error)}</Alert>
  const j = job.data
  const lesson = lessons.data?.find((l) => l.id === j.lesson_id)
  const percent = progressPercent(j.progress)
  const link = j.state === 'waiting_for_decision' ? decisionLink(j) : null
  const canCancel = !isTerminal(j.state) && !j.cancel_requested

  return (
    <Card className="flex flex-col gap-4 p-5" data-testid="job-live" data-job-id={j.id} data-state={j.state}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className={cn('mr-auto font-bold tracking-tight', compact ? 'text-base' : 'text-lg')}>{jobTypeLabel(j)}</h2>
        <JobStateBadge state={j.state} />
        {canCancel && (
          <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(j.id)}>
            Annulla job
          </Button>
        )}
      </div>
      <p className="-mt-2 text-xs text-muted-foreground">
        {lesson ? (
          <Link to={`/lezioni/${lesson.id}`} className="underline">
            {lessonTitle(lesson)}
          </Link>
        ) : (
          j.lesson_id == null && 'Lezione non ancora creata'
        )}
        {j.created_at && ` · creato alle ${formatTime(j.created_at)}`}
        {j.cancel_requested && !isTerminal(j.state) && ' · annullamento richiesto'}
      </p>

      {isActive(j.state) && (
        <div className="flex flex-col gap-1">
          <ProgressBar value={j.state === 'queued' ? 0 : percent} label="Avanzamento del job" />
          <span className="text-xs text-muted-foreground">
            {j.state === 'queued' ? 'In attesa del worker' : String(j.progress?.message ?? '') || 'In lavorazione'}
          </span>
        </div>
      )}

      {j.state === 'waiting_for_decision' && (
        <Alert tone="warning" data-testid="job-decision">
          Serve la tua approvazione: devi {decisionLabel(j.decision)}.{' '}
          {link && (
            <Link to={link} className="font-semibold underline">
              {j.decision?.kind === 'outline_approval' ? 'Rivedi la scaletta' : 'Apri la lezione'}
            </Link>
          )}
        </Alert>
      )}
      {j.state === 'failed' && j.error && <Alert tone="danger">{j.error}</Alert>}
      {j.state === 'succeeded' && j.lesson_id != null && !compact && (
        <Alert>
          Job completato.{' '}
          <Link to={`/lezioni/${j.lesson_id}`} className="font-semibold underline">
            Apri la lezione
          </Link>
        </Alert>
      )}
      {cancel.isError && <Alert tone="danger">{errorMessage(cancel.error)}</Alert>}

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Eventi</span>
          <span data-testid="stream-status" data-status={status} aria-live="polite">
            {STREAM_LABELS[status]}
          </span>
        </div>
        <ol
          role="log"
          aria-label="Eventi del job"
          className={cn('flex flex-col gap-1 overflow-y-auto rounded-lg bg-muted/60 p-3 font-mono text-xs', compact ? 'max-h-40' : 'max-h-96')}
        >
          {events.length === 0 && <li className="text-muted-foreground">Nessun evento per ora.</li>}
          {events.map((event) => {
            const { text, tone } = describeEvent(event)
            return (
              <li key={event.id} data-event-type={event.type} className={cn('flex gap-3', TONE_CLASSES[tone])}>
                <span className="shrink-0 text-muted-foreground">{formatTime(event.created_at)}</span>
                <span>{text}</span>
              </li>
            )
          })}
        </ol>
      </div>
    </Card>
  )
}
