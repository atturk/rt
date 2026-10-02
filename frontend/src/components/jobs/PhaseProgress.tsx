import { ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'
import { useNavigate } from 'react-router'

import { useJob, useJobEvents } from '@/api/jobs'
import { RetryButton } from '@/components/jobs/JobParts'
import { IconButton } from '@/components/ui/icon-button'
import { useFollowTail } from '@/lib/followTail'
import { collapseTranscription, decisionLabel, describeEvent, type Job } from '@/lib/jobs'
import { phaseProgress, progressSummary } from '@/lib/progress'
import { cn } from '@/lib/utils'

const EVENTS_KEY = 'rt-progress-events'

function storedShowEvents(): boolean {
  try {
    return localStorage.getItem(EVENTS_KEY) !== 'hidden'
  } catch {
    return true
  }
}

/** Eventi dal vivo aperti o chiusi: preferenza del browser, uguale per lezione e Job. */
function useShowEvents(): [boolean, (show: boolean) => void] {
  const [show, setShow] = useState(storedShowEvents)
  const update = (next: boolean) => {
    setShow(next)
    try {
      localStorage.setItem(EVENTS_KEY, next ? 'shown' : 'hidden')
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }
  return [show, update]
}

function formatTime(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Riga sopra le barre: fase e dettaglio, o lo stato del job quando non sta lavorando. */
function headline(job: Job, phase: string | null, detail: string | null): string {
  switch (job.state) {
    case 'queued':
      return 'In coda · in attesa del worker'
    case 'waiting_for_decision':
      return `In attesa · devi ${decisionLabel(job.decision)}`
    case 'failed':
      return `Errore${job.error ? ` · ${job.error}` : ''}`
    case 'cancelled':
      return 'Annullato'
    case 'succeeded':
      return 'Completato'
    default:
      return [phase ?? 'In lavorazione', detail].filter(Boolean).join(' · ')
  }
}

/**
 * Avanzamento del design 4.2 (schermata 03): due barre nello stesso spazio, davanti opaca il
 * totale (ogni fase pesa uguale), dietro semitrasparente la fase in corso; sopra fase e
 * dettaglio a sinistra, "fase N di M · P%" a destra e la freccia degli eventi dal vivo.
 * Con `events={false}` niente eventi (la pagina del job li mostra già).
 */
export function PhaseProgress({ jobId, events: withEvents = true, className, onRetried }: {
  jobId: string
  events?: boolean
  className?: string
  onRetried?: (jobId: string) => void
}) {
  const job = useJob(jobId)
  const [show, setShow] = useShowEvents()
  const open = withEvents && show
  const { events } = useJobEvents(open ? jobId : '', job.data, job.dataUpdatedAt)
  const logId = useId()
  const shown = collapseTranscription(events)
  const { ref, onScroll } = useFollowTail<HTMLOListElement>(shown.length)
  const navigate = useNavigate()
  if (!job.data) return <div className={cn('h-[74px] rounded-lg bg-muted', className)} aria-hidden />
  const j = job.data
  const p = phaseProgress(j)
  const summary = progressSummary(p)
  const overall = Math.round(p.overall * 100)
  const phasePercent = Math.round(p.phaseFraction * 100)
  return (
    <section
      aria-label="Avanzamento"
      data-testid="phase-progress"
      data-job-id={j.id}
      data-state={j.state}
      className={cn('rounded-lg border bg-card p-4 text-body', className)}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <b className={cn('min-w-0 flex-1 text-meta font-semibold', j.state === 'failed' && 'text-danger')} data-testid="phase-progress-title">
          {headline(j, p.phase, p.detail)}
        </b>
        <span className="text-meta tabular-nums text-muted-foreground" data-testid="phase-progress-summary">
          {summary}
        </span>
        {j.state === 'failed' && !j.retried_by && (
          <RetryButton jobId={j.id} onRetried={onRetried ?? ((id) => navigate(`/job/${id}`))} />
        )}
        {withEvents && (
          <IconButton
            label={show ? 'Nascondi eventi' : 'Mostra eventi'}
            icon={ChevronDown}
            aria-expanded={show}
            aria-controls={logId}
            className={cn('-my-2 [&_svg]:transition-transform', !show && '[&_svg]:-rotate-90')}
            onClick={() => setShow(!show)}
          />
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Avanzamento totale"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={overall}
        aria-valuetext={`${summary}${p.steps > 1 ? ` · fase al ${phasePercent}%` : ''}`}
        title={`Totale ${overall}% · fase ${phasePercent}%`}
        className="relative mt-1 h-1.5 overflow-hidden rounded-[9px] bg-muted"
      >
        <i className="absolute inset-y-0 left-0 bg-foreground opacity-25 transition-[width]" style={{ width: `${phasePercent}%` }} data-testid="phase-bar" />
        <i className="absolute inset-y-0 left-0 bg-foreground transition-[width]" style={{ width: `${overall}%` }} data-testid="overall-bar" />
      </div>
      {withEvents && (
        <ol
          id={logId}
          ref={ref}
          onScroll={onScroll}
          hidden={!show}
          role="log"
          aria-label="Eventi dal vivo"
          className="mt-3 max-h-40 overflow-y-auto border-t pt-3 font-mono text-meta leading-[1.7] text-muted-foreground"
        >
          {shown.length === 0 && <li>Nessun evento per ora.</li>}
          {shown.map((event) => (
            <li key={event.id} data-event-type={event.type}>
              {formatTime(event.created_at)} {describeEvent(event).text}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
