import { lessonTitle, type Lesson } from './format'

export type LessonNeighbors = { sameDay: { prev: Lesson | null; next: Lesson | null }; sameSubject: { prev: Lesson | null; next: Lesson | null } }
const collator = new Intl.Collator('it', { sensitivity: 'base', numeric: true })

/** Ordine cronologico, con titolo come spareggio e senza data in fondo. */
export function lessonNeighbors(lessons: Lesson[], id: number, { readyOnly }: { readyOnly: boolean }): LessonNeighbors {
  const current = lessons.find(lesson => lesson.id === id)
  const ordered = lessons.filter(lesson => lesson.id === id || !readyOnly || lesson.phases.rewrite === 'VALID').sort((a, b) => {
    if (!a.data !== !b.data) return a.data ? -1 : 1
    return (a.data || '').localeCompare(b.data || '') || (a.ora || '').localeCompare(b.ora || '') || collator.compare(lessonTitle(a), lessonTitle(b)) || a.id - b.id
  })
  const neighbors = (match: (lesson: Lesson) => boolean) => {
    const group = ordered.filter(match)
    const index = group.findIndex(lesson => lesson.id === id)
    return { prev: index > 0 ? group[index - 1] : null, next: index >= 0 ? group[index + 1] ?? null : null }
  }
  return {
    sameDay: neighbors(lesson => !!current?.data && lesson.data === current.data),
    sameSubject: neighbors(lesson => !!current?.materia && lesson.materia === current.materia),
  }
}
