import { lessonTitle, type Lesson } from './format'

/** Filtri degli elenchi di lezioni (dashboard, Recall, Immagini, Review), tenuti nell'URL. */
export type LessonListFilters = { q: string; materia: string; state: string }

const MONTHS = [
  'gennaio',
  'febbraio',
  'marzo',
  'aprile',
  'maggio',
  'giugno',
  'luglio',
  'agosto',
  'settembre',
  'ottobre',
  'novembre',
  'dicembre',
]

/** Minuscolo e senza accenti, per confronti "perché" = "perche". */
export function normalizeText(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('it')
}

/** Le forme in cui si può cercare una data ISO: 2026-09-26, 26/09/2026, 26-09-2026, 26.09.2026,
 * 26/9/2026 e 26 settembre 2026. Una data in altro formato resta com'è. */
export function dateForms(date: string): string[] {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date.trim())
  if (!m) return date ? [date] : []
  const [, y, mm, dd] = m
  const d = String(Number(dd))
  const mo = String(Number(mm))
  const month = MONTHS[Number(mm) - 1]
  return [
    `${y}-${mm}-${dd}`,
    `${dd}/${mm}/${y}`,
    `${dd}-${mm}-${y}`,
    `${dd}.${mm}.${y}`,
    `${d}/${mo}/${y}`,
    month ? `${d} ${month} ${y}` : '',
  ].filter(Boolean)
}

/** Testo in cui cerca il campo "Cerca": titolo, argomenti, materia e data (in più formati). */
export function searchableText(lesson: Lesson): string {
  return normalizeText(
    [lessonTitle(lesson), lesson.titolo, lesson.argomenti, lesson.materia, ...dateForms(lesson.data)].join('\n'),
  )
}

/** Ogni parola della ricerca deve comparire (in qualunque campo, in qualunque ordine). */
export function matchesQuery(lesson: Lesson, query: string): boolean {
  const words = normalizeText(query).split(/\s+/).filter(Boolean)
  if (words.length === 0) return true
  const haystack = searchableText(lesson)
  return words.every((w) => haystack.includes(w))
}

/** Filtro lato client sull'elenco completo già caricato (GET /lessons senza parametri). */
export function filterLessons(lessons: Lesson[], filters: Partial<LessonListFilters>): Lesson[] {
  return lessons.filter(
    (l) =>
      (!filters.materia || l.materia === filters.materia) &&
      (!filters.state || l.state === filters.state) &&
      matchesQuery(l, filters.q ?? ''),
  )
}

export const SEARCH_HELP =
  'Cerca nel titolo, negli argomenti, nella materia e nella data della lezione. La data si può scrivere come 2026-09-26, 26/09/2026 o 26 settembre 2026. Con più parole compaiono le lezioni che le contengono tutte.'
