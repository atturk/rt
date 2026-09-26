import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { lessonTitle, type Lesson } from '@/lib/format'

/** Elenco delle lezioni per scegliere su quale lavorare (recall, immagini). */
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
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{intro}</p>
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {lessons.data?.map((lesson) => (
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
