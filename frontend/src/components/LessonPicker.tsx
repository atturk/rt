import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { LessonBrowser } from '@/components/LessonBrowser'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { lessonTitle, type Lesson } from '@/lib/format'
import { Link } from 'react-router'

/** Elenco delle lezioni per scegliere su quale lavorare (Immagini), con la stessa barra della
 * dashboard: ricerca, raggruppamento, ordinamento, schede o tabella (filtro lato client). */
export function LessonPicker({
  title,
  intro,
  href,
  ready,
  notReady,
  storageKey,
}: {
  title: string
  intro: string
  href: (lesson: Lesson) => string
  ready: (lesson: Lesson) => boolean
  notReady: string
  storageKey: string
}) {
  const lessons = useLessons()
  const all = lessons.data ?? []
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{intro}</p>
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {lessons.data && all.length === 0 && <Card className="p-6 text-sm text-muted-foreground">Nessuna lezione: importane una da un audio.</Card>}
      <LessonBrowser
        storageKey={storageKey}
        lessons={all}
        card={(lesson) => (
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
        )}
        link={(lesson) => (ready(lesson) ? href(lesson) : null)}
        columns={[{ label: 'Stato', className: 'text-muted-foreground', cell: (lesson) => (ready(lesson) ? 'Pronta' : notReady) }]}
        testId="picker-lesson"
        emptyText="Nessuna lezione corrisponde ai filtri."
      />
    </section>
  )
}
