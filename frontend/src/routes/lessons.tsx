import { Brain, Download, Images, LayoutDashboard } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLesson, useLessonDocument, useLessons } from '@/api/hooks'
import { AudioPlayer } from '@/components/lesson/AudioPlayer'
import { AudioProvider } from '@/components/lesson/audio'
import { CostPanel } from '@/components/lesson/CostPanel'
import { DocumentView } from '@/components/lesson/DocumentView'
import { JobsPanel } from '@/components/lesson/JobsPanel'
import { PhasePanel } from '@/components/lesson/PhasePanel'
import { PhaseBadges } from '@/components/PhaseBadges'
import { LessonJobBanner } from '@/components/jobs/JobsIndicator'
import { LessonFilters } from '@/components/LessonFilters'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { STATE_LABELS, formatCost, lessonTitle, type Lesson } from '@/lib/format'
import type { Area } from './types'

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <Card className="flex items-baseline gap-2.5 px-4 py-2.5">
      <strong className="text-2xl font-bold tabular-nums">{value}</strong>
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
    </Card>
  )
}

function LessonCard({ lesson }: { lesson: Lesson }) {
  const meta = [lesson.materia, lesson.data, lesson.state ? STATE_LABELS[lesson.state] ?? lesson.state : null].filter(Boolean)
  return (
    <Card className="p-5" data-testid="lesson-card" data-lesson-id={lesson.id}>
      <h2 className="text-lg font-bold leading-snug tracking-tight">
        <Link to={`/lezioni/${lesson.id}`} className="hover:underline">
          {lessonTitle(lesson)}
        </Link>
      </h2>
      <p className="mb-3 mt-1 text-xs text-muted-foreground">{meta.join(' · ')}</p>
      <PhaseBadges phases={lesson.phases} />
      <div className="mt-4 flex flex-wrap items-baseline gap-3 border-t pt-3 text-xs">
        <span className="tabular-nums text-muted-foreground" title="Costo stimato">
          {formatCost(lesson.cost_usd)}
        </span>
        {lesson.pending_issues > 0 ? (
          <Link to={`/lezioni/${lesson.id}/revisione`} className="font-bold text-accent-foreground hover:underline">
            {lesson.pending_issues} issue da valutare →
          </Link>
        ) : (
          <span className="text-muted-foreground">Nessuna issue da valutare</span>
        )}
      </div>
      {lesson.error && <p className="mt-2 text-xs text-danger">{lesson.error}</p>}
    </Card>
  )
}

export function DashboardPage() {
  // Elenco completo una volta sola; testo, materia e stato si filtrano qui, senza una
  // richiesta per tasto (GET /lessons ricalcola fasi, issue e costi di ogni lezione).
  const all = useLessons()
  const lessons = all.data ?? []
  const { filters, setFilter, filtered } = useFilteredLessons(all.data)
  return (
    <section className="flex flex-col gap-5">
      <h1 className="sr-only">Dashboard</h1>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Stat value={lessons.length} label="Lezioni" />
        <Stat value={lessons.filter((l) => l.pending_issues > 0).length} label="Da rivedere" />
        <Stat value={lessons.filter((l) => l.state === 'completato').length} label="Completate" />
      </div>

      <LessonFilters lessons={lessons} filters={filters} onChange={setFilter} />

      {all.isError && <Alert tone="danger">{errorMessage(all.error)}</Alert>}
      {all.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {all.data && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {lessons.length === 0 ? 'Nessuna lezione nella cartella delle lezioni.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {filtered.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
      </div>
    </section>
  )
}

export function LessonPage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  if (lesson.isPending) return <p className="text-sm text-muted-foreground">Carico la lezione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  const l = lesson.data
  const sections = document.data?.sections ?? []
  return (
    <AudioProvider>
      <section className="flex flex-col gap-4">
        <Link to="/" className="text-xs text-muted-foreground hover:underline">
          ← Tutte le lezioni
        </Link>
        <Card className="p-5">
          <div className="flex flex-wrap items-start gap-3">
            <div className="mr-auto">
              <h1 className="text-xl font-bold tracking-tight">{lessonTitle(l)}</h1>
              <p className="mt-1 text-xs text-muted-foreground">
                {[l.materia, l.data, l.argomenti, l.state ? STATE_LABELS[l.state] ?? l.state : null].filter(Boolean).join(' · ')}
              </p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Studio">
              {l.phases.rewrite === 'VALID' && (
                <Link className={linkButton} to={`/lezioni/${id}/recall`}>
                  <Brain className="size-4" aria-hidden /> Recall
                </Link>
              )}
              {l.phases.build === 'VALID' && (
                <Link className={linkButton} to={`/lezioni/${id}/immagini`}>
                  <Images className="size-4" aria-hidden /> Immagini
                </Link>
              )}
            </div>
            {document.data?.final && (
              <div className="flex flex-wrap gap-2" aria-label="Scarica">
                <a className={linkButton} href={`/api/v1/lessons/${id}/export?format=markdown`} download>
                  <Download className="size-4" aria-hidden /> Markdown
                </a>
                <a className={linkButton} href={`/api/v1/lessons/${id}/export?format=zip&scope=all`} download>
                  <Download className="size-4" aria-hidden /> Tutti i dati (zip)
                </a>
              </div>
            )}
          </div>
          <div className="mt-3">
            <PhaseBadges phases={l.phases} />
          </div>
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t pt-3 text-xs">
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Scaletta approvata</dt>
              <dd data-testid="outline-approved">{l.outline_approved ? 'sì' : 'no'}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Segmenti</dt>
              <dd>{l.segment_count}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Issue da valutare</dt>
              <dd>
                {l.pending_issues}
                {l.phases.review && l.phases.review !== 'MISSING' && (
                  <Link to={`/lezioni/${id}/revisione`} className="ml-2 font-semibold text-accent-foreground hover:underline">
                    {l.pending_issues > 0 ? 'Rivedi →' : 'Vedi la revisione'}
                  </Link>
                )}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Costo</dt>
              <dd className="tabular-nums">{formatCost(l.cost_usd)}</dd>
            </div>
          </dl>
          {l.error && <p className="mt-2 text-xs text-danger">{l.error}</p>}
        </Card>
        <LessonJobBanner lessonId={l.id} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="flex min-w-0 flex-col gap-4">
            {l.has_audio && <AudioPlayer lessonId={id} sections={sections} />}
            <Card className="px-6 py-5">
              {document.isPending && <p className="text-sm text-muted-foreground">Carico il documento…</p>}
              {document.isError && <Alert tone="danger">{errorMessage(document.error)}</Alert>}
              {document.data && (
                <>
                  {!document.data.final && (
                    <Alert className="mb-4">Anteprima dalla bozza: il documento finale arriva con la fase Documento (build).</Alert>
                  )}
                  <DocumentView document={document.data} hasAudio={l.has_audio} lessonId={id} />
                </>
              )}
            </Card>
          </div>
          <aside className="flex flex-col gap-4">
            <PhasePanel lessonId={id} units={sections} />
            <JobsPanel lessonId={id} />
            <CostPanel lesson={l} />
          </aside>
        </div>
      </section>
    </AudioProvider>
  )
}

const linkButton =
  'inline-flex h-8 items-center gap-2 rounded-md border border-input bg-card px-3 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring'

export const lessonsArea: Area = {
  routes: [
    { index: true, element: <DashboardPage /> },
    { path: 'lezioni/:lessonId', element: <LessonPage /> },
  ],
  nav: [{ to: '/', label: 'Lezioni', icon: LayoutDashboard, end: true }],
}
