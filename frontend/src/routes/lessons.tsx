import { LayoutDashboard } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLesson, useLessons } from '@/api/hooks'
import { PhaseBadges } from '@/components/PhaseBadges'
import { LessonJobBanner } from '@/components/jobs/JobsIndicator'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
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
          <span className="font-bold text-accent-foreground">{lesson.pending_issues} issue da valutare</span>
        ) : (
          <span className="text-muted-foreground">Nessuna issue da valutare</span>
        )}
      </div>
      {lesson.error && <p className="mt-2 text-xs text-danger">{lesson.error}</p>}
    </Card>
  )
}

export function DashboardPage() {
  const [params, setParams] = useSearchParams()
  const filters = { materia: params.get('materia') ?? '', state: params.get('stato') ?? '', q: params.get('q') ?? '' }
  const all = useLessons()
  const filtered = useLessons(filters)
  const subjects = [...new Set((all.data ?? []).map((l) => l.materia).filter(Boolean))].sort()

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const lessons = all.data ?? []
  return (
    <section className="flex flex-col gap-5">
      <h1 className="sr-only">Dashboard</h1>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Stat value={lessons.length} label="Lezioni" />
        <Stat value={lessons.filter((l) => l.pending_issues > 0).length} label="Da rivedere" />
        <Stat value={lessons.filter((l) => l.state === 'completato').length} label="Completate" />
      </div>

      <form className="grid grid-cols-1 gap-3 sm:grid-cols-3" role="search" onSubmit={(e) => e.preventDefault()}>
        <div className="flex flex-col gap-1">
          <Label htmlFor="filter-q">Cerca</Label>
          <Input
            id="filter-q"
            type="search"
            placeholder="Titolo, argomenti, cartella"
            value={filters.q}
            onChange={(e) => setFilter('q', e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="filter-materia">Materia</Label>
          <Select id="filter-materia" value={filters.materia} onChange={(e) => setFilter('materia', e.target.value)}>
            <option value="">Tutte</option>
            {subjects.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="filter-stato">Stato</Label>
          <Select id="filter-stato" value={filters.state} onChange={(e) => setFilter('stato', e.target.value)}>
            <option value="">Tutti</option>
            {Object.entries(STATE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </form>

      {filtered.isError && <Alert tone="danger">{errorMessage(filtered.error)}</Alert>}
      {filtered.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {filtered.data?.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {lessons.length === 0 ? 'Nessuna lezione nella cartella delle lezioni.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {filtered.data?.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
      </div>
    </section>
  )
}

/** Intestazione della lezione; documento, audio e azioni arrivano con RT4-F2. */
export function LessonPage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  if (lesson.isPending) return <p className="text-sm text-muted-foreground">Carico la lezione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  const l = lesson.data
  return (
    <section className="flex flex-col gap-4">
      <Link to="/" className="text-xs text-muted-foreground hover:underline">
        ← Tutte le lezioni
      </Link>
      <Card className="p-5">
        <h1 className="text-xl font-bold tracking-tight">{lessonTitle(l)}</h1>
        <p className="mb-3 mt-1 text-xs text-muted-foreground">
          {[l.materia, l.data, l.state ? STATE_LABELS[l.state] ?? l.state : null].filter(Boolean).join(' · ')}
        </p>
        <PhaseBadges phases={l.phases} />
      </Card>
      <LessonJobBanner lessonId={l.id} />
    </section>
  )
}

export const lessonsArea: Area = {
  routes: [
    { index: true, element: <DashboardPage /> },
    { path: 'lezioni/:lessonId', element: <LessonPage /> },
  ],
  nav: [{ to: '/', label: 'Lezioni', icon: LayoutDashboard, end: true }],
}
