import { useEffect, useRef } from 'react'

import { errorMessage } from '@/api/client'
import { isActiveJob, useCancelJob, useLessonJobs, useRefreshLesson } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { PHASE_LABELS, type Tone } from '@/lib/format'

const JOB_STATES: Record<string, [string, Tone]> = {
  queued: ['in coda', 'neutral'],
  running: ['in corso', 'warning'],
  waiting_for_decision: ['serve una tua decisione', 'warning'],
  succeeded: ['completato', 'success'],
  failed: ['fallito', 'danger'],
  cancelled: ['annullato', 'neutral'],
}

const JOB_TYPES: Record<string, string> = {
  run_pipeline: 'Pipeline completa',
  run_phase: 'Fase',
  rewrite_unit: 'Rielaborazione unità',
  ingest_audio: 'Importazione audio',
  add_images: 'Immagini',
  outline_revision: 'Revisione scaletta',
}

function jobLabel(type: string, payload: Record<string, unknown>): string {
  const phase = typeof payload.phase === 'string' ? PHASE_LABELS[payload.phase] ?? payload.phase : null
  const unit = typeof payload.unit === 'string' ? ` ${payload.unit}` : ''
  if (type === 'run_phase' && phase) return `${phase}${unit}`
  return (JOB_TYPES[type] ?? type) + unit
}

/**
 * Job della lezione con avanzamento (polling di GET /jobs; lo stream SSE arriva con F4).
 * Quando un job finisce la pagina rilegge lezione, fasi, documento e costi dall'API.
 */
export function JobsPanel({ lessonId }: { lessonId: number }) {
  const jobs = useLessonJobs(lessonId)
  const cancel = useCancelJob(lessonId)
  const refresh = useRefreshLesson(lessonId)
  const active = useRef<Set<string>>(new Set())

  useEffect(() => {
    const now = new Set((jobs.data ?? []).filter((j) => isActiveJob(j.state)).map((j) => j.id))
    const finished = [...active.current].some((id) => !now.has(id))
    active.current = now
    if (finished) void refresh()
  }, [jobs.data, refresh])

  if (!jobs.data?.length) return null
  return (
    <Card className="flex flex-col gap-2 p-4" data-testid="jobs-panel">
      <h2 className="text-sm font-bold">Job recenti</h2>
      <ul className="flex flex-col gap-2">
        {jobs.data.slice(0, 5).map((job) => {
          const [label, tone] = JOB_STATES[job.state] ?? [job.state, 'neutral']
          const p = job.progress as { phase?: string; current?: number; total?: number; message?: string } | null
          return (
            <li key={job.id} className="flex flex-col gap-1 text-xs" data-job-state={job.state}>
              <div className="flex items-center gap-2">
                <span className="font-semibold">{jobLabel(job.type, job.payload)}</span>
                <Badge tone={tone}>{label}</Badge>
                {isActiveJob(job.state) && (
                  <Button variant="ghost" size="sm" className="ml-auto h-6" disabled={job.cancel_requested} onClick={() => cancel.mutate(job.id)}>
                    {job.cancel_requested ? 'Annullamento…' : 'Annulla'}
                  </Button>
                )}
              </div>
              {job.state === 'running' && p && (
                <div>
                  <span className="text-muted-foreground">
                    {[p.phase ? PHASE_LABELS[p.phase] ?? p.phase : null, p.total ? `${p.current ?? 0}/${p.total}` : null, p.message]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {p.total ? (
                    <progress className="mt-1 block h-1.5 w-full" value={p.current ?? 0} max={p.total} aria-label="Avanzamento" />
                  ) : null}
                </div>
              )}
              {job.error && <span className="text-danger">{job.error}</span>}
            </li>
          )
        })}
      </ul>
      {cancel.isError && <Alert tone="danger">{errorMessage(cancel.error)}</Alert>}
    </Card>
  )
}
