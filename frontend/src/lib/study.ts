import { lessonTitle, type Lesson } from './format'
import type { LessonGroup } from './lessonView'
import type { LessonsGrouping } from './lessonsPage'

/** Gruppo dello Studio: le lezioni di un giorno, di una materia o di un docente. */
export type StudyScope = { kind: 'giorno' | 'materia' | 'docente'; value: string }

const KIND: Record<LessonsGrouping, StudyScope['kind']> = { data: 'giorno', materia: 'materia', docente: 'docente' }

/** Indirizzo dello Studio di un gruppo di Lezioni (null se il gruppo non ha una chiave: senza data, materia o docente). */
export function groupStudyPath(group: Pick<LessonGroup, 'key'>, grouping: LessonsGrouping): string | null {
  return group.key ? `/studio/${KIND[grouping]}/${encodeURIComponent(group.key)}` : null
}

/** Lezioni pronte (rielaborazione valida) del gruppo, nell'ordine in cui si studiano: dalla più vecchia. */
export function studyLessons(lessons: Lesson[], scope: StudyScope): Lesson[] {
  const value = scope.value.trim()
  const pick = (l: Lesson) =>
    scope.kind === 'giorno' ? l.data === value : scope.kind === 'materia' ? l.materia === value : (l.docente ?? '').trim() === value
  return lessons
    .filter((l) => pick(l) && l.phases.rewrite === 'VALID')
    .sort((a, b) => (a.data || '').localeCompare(b.data || '') || lessonTitle(a).localeCompare(lessonTitle(b)) || a.id - b.id)
}
