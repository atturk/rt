import { Activity, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLesson, useLessons } from '@/api/hooks'
import { useApproveOutline, useCreateLesson, useJobs, useOutline, useReviseOutline } from '@/api/jobs'
import { JobLive } from '@/components/jobs/JobLive'
import { JobStateBadge, ProgressBar, WorkerWarning } from '@/components/jobs/JobParts'
import { JobsIndicator } from '@/components/jobs/JobsIndicator'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { lessonTitle } from '@/lib/format'
import { AUDIO_EXTENSIONS, JOB_STATE_LABELS, audioFileProblem, decisionLabel, decisionLink, formatBytes, jobTypeLabel } from '@/lib/jobs'
import type { Area } from './types'

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function Checkbox({ id, label, hint, checked, onChange }: { id: string; label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start gap-2">
      <input id={id} type="checkbox" className="mt-0.5 size-4 accent-current" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <label htmlFor={id} className="text-sm">
        {label}
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </label>
    </div>
  )
}

// ---------------------------------------------------------------- importazione

/** Come 'rt setup' (solo importazione e trascrizione) o 'rt run audio' (pipeline completa). */
export function ImportPage() {
  const navigate = useNavigate()
  const lessons = useLessons()
  const create = useCreateLesson()
  const [files, setFiles] = useState<File[]>([])
  const [date, setDate] = useState(today())
  const [materia, setMateria] = useState('')
  const [argomenti, setArgomenti] = useState('')
  const [run, setRun] = useState(true)
  const [mock, setMock] = useState(false)
  const [autoAccept, setAutoAccept] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const subjects = [...new Set((lessons.data ?? []).map((l) => l.materia).filter(Boolean))].sort()

  function submit(event: FormEvent) {
    event.preventDefault()
    const issue = audioFileProblem(files) ?? (materia.trim() ? null : 'Indica la materia.')
    setProblem(issue)
    if (issue) return
    create.mutate(
      { files, date, materia: materia.trim(), argomenti: argomenti.trim(), run, mock, auto_accept: autoAccept },
      { onSuccess: (accepted) => navigate(`/job/${accepted.job_id}`) },
    )
  }

  const total = files.reduce((sum, f) => sum + f.size, 0)
  const progress = create.progress
  const percent = progress?.total ? Math.round((progress.loaded / progress.total) * 100) : null
  const uploadError = create.error instanceof ApiError && create.error.code === 'payload_too_large'
    ? `${create.error.message} Dividi l'audio o alza RT_API_MAX_UPLOAD_MB.`
    : create.isError ? errorMessage(create.error) : null

  return (
    <section className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">Importa una lezione</h1>
      <WorkerWarning />
      <Card className="p-5">
        <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Importa una lezione">
          <div className="flex flex-col gap-1">
            <Label htmlFor="import-audio">File audio</Label>
            <Input
              id="import-audio"
              type="file"
              multiple
              accept={[...AUDIO_EXTENSIONS, 'audio/*'].join(',')}
              className="h-auto py-1.5"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              disabled={create.isPending}
            />
            <span className="text-xs text-muted-foreground">
              {files.length > 0
                ? `${files.length} file, ${formatBytes(total)}. Più file diventano un'unica lezione, nell'ordine scelto.`
                : `Formati: ${AUDIO_EXTENSIONS.join(', ')}.`}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="import-date">Data</Label>
              <Input id="import-date" type="date" required value={date} onChange={(e) => setDate(e.target.value)} disabled={create.isPending} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="import-materia">Materia</Label>
              <Input
                id="import-materia"
                list="import-materie"
                required
                value={materia}
                onChange={(e) => setMateria(e.target.value)}
                placeholder="Es. BIOCHIMICA"
                disabled={create.isPending}
              />
              <datalist id="import-materie">
                {subjects.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="import-argomenti">Argomenti</Label>
            <Input
              id="import-argomenti"
              value={argomenti}
              onChange={(e) => setArgomenti(e.target.value)}
              placeholder="Facoltativi: se mancano li ricava la pipeline"
              disabled={create.isPending}
            />
          </div>
          <Checkbox
            id="import-run"
            label="Avvia subito la pipeline"
            hint="Trascrizione, preparazione, scaletta (con la tua approvazione), rielaborazione, review e documento, come 'rt run'. Senza, solo importazione e trascrizione, come 'rt setup'."
            checked={run}
            onChange={setRun}
          />
          <details className="text-sm">
            <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">Opzioni avanzate</summary>
            <div className="mt-3 flex flex-col gap-3">
              <Checkbox
                id="import-mock"
                label="Modalità prova (mock)"
                hint="Nessuna trascrizione reale né chiamata ai modelli, come 'rt run --mock'."
                checked={mock}
                onChange={setMock}
              />
              <Checkbox
                id="import-auto-accept"
                label="Accetta automaticamente le correzioni della review"
                hint="Come 'rt run --auto-accept'."
                checked={autoAccept}
                onChange={setAutoAccept}
              />
            </div>
          </details>
          {problem && <Alert tone="danger">{problem}</Alert>}
          {uploadError && <Alert tone="danger">{uploadError}</Alert>}
          {progress && (
            <div className="flex flex-col gap-1">
              <ProgressBar value={percent} label="Caricamento dell'audio" />
              <span className="text-xs text-muted-foreground" aria-live="polite">
                Caricamento: {formatBytes(progress.loaded)}
                {progress.total ? ` di ${formatBytes(progress.total)} (${percent}%)` : ''}
              </span>
            </div>
          )}
          <div>
            <Button type="submit" disabled={create.isPending}>
              <Upload aria-hidden />
              {create.isPending ? 'Caricamento…' : 'Importa'}
            </Button>
          </div>
        </form>
      </Card>
    </section>
  )
}

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
  const jobs = useJobs({ state: state || undefined, lesson_id: lessonId, limit: 100 }, { poll: 5_000 })
  const lessons = useLessons()
  const byId = new Map((lessons.data ?? []).map((l) => [l.id, l]))

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-bold tracking-tight">Job</h1>
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
        <Link to="/importa" className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90">
          <Upload className="size-4" aria-hidden />
          Importa
        </Link>
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
              </Card>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function JobPage() {
  const jobId = useParams().jobId ?? ''
  return (
    <section className="flex flex-col gap-4">
      <Link to="/job" className="text-xs text-muted-foreground hover:underline">
        ← Tutti i job
      </Link>
      <h1 className="sr-only">Dettaglio del job</h1>
      <WorkerWarning />
      <JobLive jobId={jobId} />
    </section>
  )
}

// ---------------------------------------------------------------- outline

/** Scaletta ad albero, approvazione e richiesta di modifiche (come la revisione da terminale). */
export function OutlinePage() {
  const lessonId = Number(useParams().lessonId)
  const lesson = useLesson(lessonId)
  const outline = useOutline(lessonId)
  const approve = useApproveOutline(lessonId)
  const revise = useReviseOutline(lessonId)
  const waitingJobs = useJobs({ lesson_id: lessonId, state: 'waiting_for_decision' }, { poll: 5_000 })
  const waiting = waitingJobs.data?.find((j) => j.decision?.kind === 'outline_approval')
  const [feedback, setFeedback] = useState('')
  const [mock, setMock] = useState(false)
  const [resumedJob, setResumedJob] = useState<string | null>(null)
  const [revisionJob, setRevisionJob] = useState<string | null>(null)

  function doApprove() {
    const pending = waiting?.id ?? null
    approve.mutate(undefined, { onSuccess: () => setResumedJob(pending) })
  }

  function doRevise(event: FormEvent) {
    event.preventDefault()
    if (!feedback.trim()) return
    revise.mutate(
      { feedback: feedback.trim(), mock },
      {
        onSuccess: (accepted) => {
          setRevisionJob(accepted.job_id)
          setFeedback('')
        },
      },
    )
  }

  const notFound = outline.error instanceof ApiError && outline.error.code === 'outline_not_found'
  const busy = [approve.error, revise.error].find((e) => e instanceof ApiError && e.code === 'lesson_busy')
  const otherError = [approve.error, revise.error].find((e) => e && e !== busy)

  return (
    <section className="flex flex-col gap-4">
      <Link to={`/lezioni/${lessonId}`} className="text-xs text-muted-foreground hover:underline">
        ← {lesson.data ? lessonTitle(lesson.data) : 'Lezione'}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-xl font-bold tracking-tight">Scaletta</h1>
        {outline.data && (
          <Badge tone={outline.data.approved ? 'success' : 'warning'} data-testid="outline-approved" data-approved={outline.data.approved}>
            {outline.data.approved ? 'Approvata' : 'Da approvare'}
          </Badge>
        )}
      </div>

      {waiting && !outline.data?.approved && (
        <Alert tone="warning" data-testid="outline-waiting">
          <strong>Serve la tua approvazione:</strong> la pipeline è ferma finché non approvi la scaletta o chiedi modifiche.
        </Alert>
      )}
      {resumedJob && (
        <Alert data-testid="pipeline-resumed">
          Scaletta approvata: la pipeline è ripartita.{' '}
          <Link to={`/job/${resumedJob}`} className="font-semibold underline">
            Segui il job
          </Link>
        </Alert>
      )}
      {busy && <Alert tone="warning">{errorMessage(busy)} Riprova quando il job in corso ha finito.</Alert>}
      {otherError && <Alert tone="danger">{errorMessage(otherError)}</Alert>}

      {outline.isPending && <p className="text-sm text-muted-foreground">Carico la scaletta…</p>}
      {notFound && <Card className="p-6 text-sm text-muted-foreground">La scaletta non è ancora stata generata: avvia la pipeline o la fase scaletta.</Card>}
      {outline.isError && !notFound && <Alert tone="danger">{errorMessage(outline.error)}</Alert>}

      {outline.data && (
        <>
          <Card className="p-5">
            <h2 className="mb-3 text-lg font-bold tracking-tight">{outline.data.lesson_title}</h2>
            <ol className="flex flex-col gap-3" aria-label="Scaletta della lezione">
              {outline.data.macro_sections.map((macro) => (
                <li key={macro.id} data-testid="outline-macro">
                  <details open>
                    <summary className="cursor-pointer font-semibold">
                      <span className="mr-2 text-xs text-muted-foreground">{macro.id}</span>
                      {macro.title}
                    </summary>
                    <ol className="ml-5 mt-2 flex flex-col gap-2 border-l pl-4">
                      {macro.units.map((unit) => (
                        <li key={unit.id} data-testid="outline-unit">
                          <p className="text-sm font-medium">
                            <span className="mr-2 text-xs text-muted-foreground">{unit.id}</span>
                            {unit.title}
                          </p>
                          {unit.key_concepts.length > 0 && (
                            <p className="text-xs text-muted-foreground">{unit.key_concepts.join(' · ')}</p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </details>
                </li>
              ))}
            </ol>
          </Card>

          <Card className="flex flex-col gap-4 p-5">
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={doApprove} disabled={approve.isPending || outline.data.approved}>
                {outline.data.approved ? 'Scaletta approvata' : 'Approva la scaletta'}
              </Button>
              {outline.data.approval?.approved_at != null && (
                <span className="text-xs text-muted-foreground">Approvata il {formatDateTime(String(outline.data.approval.approved_at))}</span>
              )}
            </div>
            <form className="flex flex-col gap-2" onSubmit={doRevise} aria-label="Richiedi modifiche alla scaletta">
              <Label htmlFor="outline-feedback">Richiedi modifiche</Label>
              <textarea
                id="outline-feedback"
                rows={3}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Es. Dividi la seconda sezione in due unità"
                className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
              />
              <Checkbox id="outline-mock" label="Modalità prova (mock)" checked={mock} onChange={setMock} />
              <div>
                <Button type="submit" variant="outline" disabled={revise.isPending || !feedback.trim()}>
                  Rigenera con il feedback
                </Button>
              </div>
            </form>
          </Card>
        </>
      )}
      {revisionJob && <JobLive jobId={revisionJob} compact />}
    </section>
  )
}

export const jobsArea: Area = {
  routes: [
    { path: 'importa', element: <ImportPage /> },
    { path: 'job', element: <JobsPage /> },
    { path: 'job/:jobId', element: <JobPage /> },
    { path: 'lezioni/:lessonId/outline', element: <OutlinePage /> },
  ],
  nav: [
    { to: '/importa', label: 'Importa', icon: Upload },
    { to: '/job', label: 'Job', icon: Activity },
  ],
  header: JobsIndicator,
}
