import { lessonTitle, type Lesson } from './format'

/**
 * Come si guarda l'elenco delle lezioni: vista (schede o tabella), ordinamento e raggruppamento.
 * Sono preferenze di chi usa il browser, non filtri: restano in localStorage e non nell'URL,
 * così un link condiviso porta i filtri ma non impone la vista.
 */
export type LessonViewMode = 'schede' | 'tabella'
export type LessonSortKey = 'data' | 'titolo' | 'materia' | 'stato' | 'issue' | 'costo'
export type SortDir = 'asc' | 'desc'
export type LessonGroupBy = 'nessuno' | 'giorno' | 'mese' | 'materia' | 'docente'

export type LessonViewPrefs = {
  view: LessonViewMode
  sort: LessonSortKey
  dir: SortDir
  group: LessonGroupBy
  /** Gruppi chiusi, come `<raggruppamento>:<chiave>`. */
  collapsed: string[]
}

export const DEFAULT_VIEW_PREFS: LessonViewPrefs = { view: 'schede', sort: 'data', dir: 'desc', group: 'nessuno', collapsed: [] }

export const SORT_LABELS: Record<LessonSortKey, string> = {
  data: 'Data',
  titolo: 'Titolo',
  materia: 'Materia',
  stato: 'Stato',
  issue: 'Issue da valutare',
  costo: 'Costo',
}

export const GROUP_LABELS: Record<LessonGroupBy, string> = {
  nessuno: 'Nessuno',
  giorno: 'Giorno',
  mese: 'Mese',
  materia: 'Materia',
  docente: 'Docente',
}

/** Direzione naturale al primo clic: date, issue e costi dal più alto; testi dalla A. */
export const DEFAULT_DIR: Record<LessonSortKey, SortDir> = {
  data: 'desc',
  titolo: 'asc',
  materia: 'asc',
  stato: 'asc',
  issue: 'desc',
  costo: 'desc',
}

// Ordine del flusso di lavoro, non alfabetico: "Da rivedere" vicino a "Pronta per il documento".
const STATE_ORDER = [
  'fallito',
  'metadata_only',
  'setup_completato',
  'preparato',
  'outline_validata',
  'draft_validato',
  'revisione_completata',
  'in_attesa_revisione_umana',
  'pronto_per_build',
  'completato',
]

const collator = new Intl.Collator('it', { sensitivity: 'base', numeric: true })

function stateRank(state: string | null | undefined): number {
  const index = STATE_ORDER.indexOf(state ?? '')
  return index < 0 ? STATE_ORDER.length : index
}

function compareBy(key: LessonSortKey, a: Lesson, b: Lesson): number {
  switch (key) {
    case 'data':
      return (a.data || '').localeCompare(b.data || '') || (a.ora || '').localeCompare(b.ora || '')
    case 'titolo':
      return collator.compare(lessonTitle(a), lessonTitle(b))
    case 'materia':
      return collator.compare(a.materia || '', b.materia || '')
    case 'stato':
      return stateRank(a.state) - stateRank(b.state)
    case 'issue':
      return a.pending_issues - b.pending_issues
    case 'costo':
      return (a.cost_usd ?? 0) - (b.cost_usd ?? 0)
  }
}

/**
 * Ordina senza toccare l'originale. A parità vale la data (più recente prima) e poi il nome della
 * cartella, come l'API: con l'ordinamento di partenza l'elenco resta quello di GET /lessons.
 * Le lezioni senza data finiscono in fondo in entrambe le direzioni.
 */
export function sortLessons(lessons: Lesson[], key: LessonSortKey, dir: SortDir): Lesson[] {
  const sign = dir === 'asc' ? 1 : -1
  return [...lessons].sort((a, b) => {
    if (key === 'data' && !a.data !== !b.data) return a.data ? -1 : 1
    return (
      sign * compareBy(key, a, b) ||
      (b.data || '').localeCompare(a.data || '') ||
      (b.ora || '').localeCompare(a.ora || '') ||
      b.folder_name.localeCompare(a.folder_name)
    )
  })
}

export type LessonGroup = { key: string; label: string; lessons: Lesson[] }

const NO_DATE = 'Senza data'
const NO_SUBJECT = 'Senza materia'
const NO_TEACHER = 'Senza docente'

function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function capitalize(text: string): string {
  return text.charAt(0).toLocaleUpperCase('it') + text.slice(1)
}

function parseIso(date: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date.trim())
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
}

/** "Oggi · lunedì 29 settembre", "Ieri · …", "Mercoledì 3 settembre 2025" (anno solo se non è quello corrente). */
export function dayLabel(date: string, now = new Date()): string {
  const d = parseIso(date)
  if (!d) return date || NO_DATE
  const sameYear = d.getFullYear() === now.getFullYear()
  const text = d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', ...(sameYear ? {} : { year: 'numeric' }) })
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  if (date.startsWith(isoDay(now))) return `Oggi · ${text}`
  if (date.startsWith(isoDay(yesterday))) return `Ieri · ${text}`
  return capitalize(text)
}

/** "Settembre 2026". */
export function monthLabel(date: string): string {
  const d = parseIso(date)
  if (!d) return date || NO_DATE
  return capitalize(d.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' }))
}

/**
 * Raggruppa l'elenco già ordinato: dentro ogni gruppo resta l'ordine scelto. I gruppi per data
 * seguono la direzione dell'ordinamento per data (altrimenti i più recenti prima); materie e
 * docenti vanno in ordine alfabetico. "Senza data", "Senza materia" e "Senza docente" stanno in fondo.
 */
export function groupLessons(sorted: Lesson[], group: LessonGroupBy, dateDir: SortDir = 'desc', now = new Date()): LessonGroup[] {
  if (group === 'nessuno') return [{ key: 'tutte', label: 'Tutte le lezioni', lessons: sorted }]
  const keyOf = (l: Lesson): string => {
    if (group === 'materia') return l.materia || ''
    if (group === 'docente') return (l.docente ?? '').trim()
    const d = parseIso(l.data || '')
    if (!d) return ''
    return group === 'giorno' ? isoDay(d) : isoDay(d).slice(0, 7)
  }
  const groups = new Map<string, Lesson[]>()
  for (const lesson of sorted) {
    const key = keyOf(lesson)
    groups.set(key, [...(groups.get(key) ?? []), lesson])
  }
  const byName = group === 'materia' || group === 'docente'
  const sign = byName || dateDir === 'asc' ? 1 : -1
  const empty = group === 'materia' ? NO_SUBJECT : group === 'docente' ? NO_TEACHER : NO_DATE
  return [...groups.entries()]
    .sort(([a], [b]) => (!a !== !b ? (a ? -1 : 1) : sign * (byName ? collator.compare(a, b) : a.localeCompare(b))))
    .map(([key, lessons]) => ({
      key,
      label: !key ? empty : byName ? key : group === 'giorno' ? dayLabel(key, now) : monthLabel(`${key}-01`),
      lessons,
    }))
}


function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

/** Legge le preferenze salvate scartando i valori sconosciuti (versioni vecchie, modifiche a mano). */
export function parseViewPrefs(raw: string | null): LessonViewPrefs {
  let data: Record<string, unknown> = {}
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>
  } catch {
    /* preferenze illeggibili: si riparte da quelle predefinite */
  }
  const d = DEFAULT_VIEW_PREFS
  return {
    view: pick(data.view, ['schede', 'tabella'], d.view),
    sort: pick(data.sort, Object.keys(SORT_LABELS) as LessonSortKey[], d.sort),
    dir: pick(data.dir, ['asc', 'desc'], d.dir),
    group: pick(data.group, Object.keys(GROUP_LABELS) as LessonGroupBy[], d.group),
    collapsed: Array.isArray(data.collapsed) ? data.collapsed.filter((c): c is string => typeof c === 'string').slice(-200) : [],
  }
}
