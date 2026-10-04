import { Link, useParams, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { useJobs } from '@/api/jobs'
import { JobLive } from '@/components/jobs/JobLive'
import { JobStateBadge, WorkerWarning } from '@/components/jobs/JobParts'
import { PhaseProgress } from '@/components/jobs/PhaseProgress'
import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { lessonTitle } from '@/lib/format'
import { JOB_STATE_LABELS, decisionLabel, decisionLink, isActive, jobTypeLabel } from '@/lib/jobs'

// ---------------------------------------------------------------- job

function formatDateTime(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
}

export function JobsPage() {
  const [params, setParams] = useSearchParams()
  const state = params.get('stato') ?? ''
  const lessonParam = params.get('lezione')
  const lessonId = lessonParam ? Number(lessonParam) : undefined
  const jobs = useJobs({ state: state || undefined, lesson_id: lessonId, limit: 100 })
  const lessons = useLessons()
  const byId = new Map((lessons.data ?? []).map((l) => [l.id, l]))

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <>
    <PageHeader title="Job in corso" />
    <PageBody>
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="jobs-stato">Stato</Label>
          <Select id="jobs-stato" value={state} onChange={(e) => setFilter('stato', e.target.value)} className="w-56">
            <option value="">Tutti</option>
            {Object.entries(JOB_STATE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {lessonId != null && (
        <p className="text-xs text-muted-foreground">
          Solo la lezione {byId.get(lessonId) ? lessonTitle(byId.get(lessonId)!) : lessonId}.{' '}
          <button type="button" className="underline" onClick={() => setFilter('lezione', '')}>
            Mostra tutti
          </button>
        </p>
      )}
      <WorkerWarning />
      {jobs.isError && <Alert tone="danger">{errorMessage(jobs.error)}</Alert>}
      {jobs.isPending && <p className="text-sm text-muted-foreground">Carico i job…</p>}
      {jobs.data?.length === 0 && <Card className="p-6 text-sm text-muted-foreground">Nessun job.</Card>}
      <ul className="flex flex-col gap-2" aria-label="Elenco dei job">
        {jobs.data?.map((job) => {
          const lesson = job.lesson_id != null ? byId.get(job.lesson_id) : undefined
          const link = job.state === 'waiting_for_decision' ? decisionLink(job) : null
          return (
            <li key={job.id}>
              <Card className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3" data-testid="job-row" data-job-id={job.id} data-state={job.state}>
                <Link to={`/job/${job.id}`} className="font-semibold hover:underline">
                  {jobTypeLabel(job)}
                </Link>
                <span className="text-xs text-muted-foreground">{lesson ? lessonTitle(lesson) : job.lesson_id == null ? 'Nuova lezione' : ''}</span>
                <span className="text-xs text-muted-foreground">{formatDateTime(job.created_at)}</span>
                <span className="ml-auto flex items-center gap-2">
                  {link && (
                    <Link to={link} className="text-xs font-semibold text-warning underline">
                      Devi {decisionLabel(job.decision)}
                    </Link>
                  )}
                  <JobStateBadge state={job.state} />
                </span>
                {isActive(job.state) && <PhaseProgress jobId={job.id} className="basis-full" />}
              </Card>
            </li>
          )
        })}
      </ul>
    </section>
    </PageBody>
    </>
  )
}

export function JobPage() {
  const jobId = useParams().jobId ?? ''
  return (
    <>
      <PageHeader title="Dettaglio del job" back={{ to: '/job', label: 'Tutti i job' }} />
      <PageBody>
        <section className="flex flex-col gap-4">
          <WorkerWarning />
          <JobLive jobId={jobId} />
        </section>
      </PageBody>
    </>
  )
}

