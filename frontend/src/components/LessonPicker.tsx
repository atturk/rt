import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { LessonFilters } from '@/components/LessonFilters'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { lessonTitle, type Lesson } from '@/lib/format'

/** Elenco delle lezioni per scegliere su quale lavorare (recall, immagini), con la stessa barra
 * di ricerca della dashboard (filtro lato client sull'elenco completo). */
export function LessonPicker({
  title,
  intro,
  href,
  ready,
  notReady,
}: {
  title: string
  intro: string
  href: (lesson: Lesson) => string
  ready: (lesson: Lesson) => boolean
  notReady: string
}) {
  const lessons = useLessons()
  const { filters, setFilter, filtered } = useFilteredLessons(lessons.data)
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{intro}</p>
      <LessonFilters lessons={lessons.data ?? []} filters={filters} onChange={setFilter} />
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {lessons.data && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {lessons.data.length === 0 ? 'Nessuna lezione nella cartella delle lezioni.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {filtered.map((lesson) => (
          <li key={lesson.id}>
            <Card className="flex flex-col gap-1 p-4" data-testid="picker-lesson" data-lesson-id={lesson.id}>
              {ready(lesson) ? (
                <Link to={href(lesson)} className="font-semibold hover:underline">
                  {lessonTitle(lesson)}
                </Link>
              ) : (
                <span className="font-semibold text-muted-foreground">{lessonTitle(lesson)}</span>
              )}
              <span className="text-xs text-muted-foreground">
                {[lesson.materia, lesson.data].filter(Boolean).join(' · ')}
                {!ready(lesson) && ` · ${notReady}`}
              </span>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  )
}
