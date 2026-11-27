import { useCallback, useMemo, useState } from 'react'

import type { CalendarMissingLessons, CalendarToRecoverItem } from '@/api/calendar'
import { STATE_LABELS, formatCost, lessonTitle, type Lesson } from './format'
import { dayLabel, groupLessons, monthLabel, sortLessons, type LessonGroup } from './lessonView'
import { usePreference } from './preferences'

/**
 * Pagina Lezioni del design 4.2 (schermate 01, 01b, 01c, 04): elenco a righe raggruppato per
 * data, materia o docente. Sotto il titolo solo i campi che il gruppo non dice già; il resto
 * sta nel popup Info.
 */
export type LessonsGrouping = 'data' | 'mese' | 'materia' | 'docente' | 'nessuno'
export type LessonsSort = 'recenti' | 'meno-recenti' | 'ricreate' | 'titolo' | 'studio-recente' | 'piu-avanti' | 'piu-indietro'

export const GROUPING_LABELS: Record<LessonsGrouping, string> = { data: 'Per data', mese: 'Per mese', materia: 'Per materia', docente: 'Per docente', nessuno: 'Senza gruppi' }
export const GROUP_CYCLE: LessonsGrouping[] = ['data', 'mese', 'materia', 'docente', 'nessuno']
export const PHONE_GROUP_LABELS: Record<LessonsGrouping, string> = { data: 'Data', mese: 'Mese', materia: 'Materia', docente: 'Docente', nessuno: 'Nessuno' }

export const SORT_OPTIONS: Record<LessonsSort, string> = {
  recenti: 'Dalla più recente',
  'meno-recenti': 'Dalla meno recente',
  ricreate: '(Ri)create di recente',
  titolo: 'Per titolo',
  'studio-recente': 'Studiate di recente',
  'piu-avanti': 'Più avanti nello studio',
  'piu-indietro': 'Più indietro nello studio',
}
export const SORT_CYCLE: LessonsSort[] = ['recenti', 'meno-recenti', 'ricreate', 'titolo', 'studio-recente', 'piu-avanti', 'piu-indietro']
export const PHONE_SORT_LABELS: Record<LessonsSort, string> = {
  recenti: 'Recenti', 'meno-recenti': 'Vecchie', ricreate: 'Create', titolo: 'A–Z',
  'studio-recente': 'Studio', 'piu-avanti': 'Avanti', 'piu-indietro': 'Indietro',
}

/** Sfondo del gruppo n-esimo secondo la preferenza (variabili --group-* in index.css). */
export function groupBackground(index: number, mode: string | undefined): string | undefined {
  if (mode === 'niente') return undefined
  if (mode === 'grigi') return 'var(--group-gray)'
  return `var(--group-${(index % 4) + 1})`
}

export type PinnableGrouping = Exclude<LessonsGrouping, 'nessuno'>
export type CategoryPins = Partial<Record<PinnableGrouping, string>>
export const CATEGORY_PINS_PREF = 'lessons.pins'
export const LEGACY_PINNED_VIEW_PREF = 'lessons.pinned'

const PINNABLE_GROUPINGS: readonly PinnableGrouping[] = ['data', 'mese', 'materia', 'docente']

export function isPinnableGrouping(group: LessonsGrouping): group is PinnableGrouping {
  return group === 'data' || group === 'mese' || group === 'materia' || group === 'docente'
}

export function parseCategoryPins(raw: unknown): CategoryPins {
  try {
    let data = raw
    if (typeof raw === 'string') {
      data = JSON.parse(raw)
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {}
    const result: CategoryPins = {}
    for (const grouping of PINNABLE_GROUPINGS) {
      const value = (data as Record<string, unknown>)[grouping]
      if (typeof value === 'string') {
        result[grouping] = value
      }
    }
    return result
  } catch {
    return {}
  }
}

export function categoryPinLabel(grouping: PinnableGrouping, key: string, now = new Date()): string {
  switch (grouping) {
    case 'data':
      return key ? dayLabel(key, now) : 'Senza data'
    case 'mese':
      return key ? monthLabel(`${key}-01`) : 'Senza data'
    case 'materia':
      return key ? subjectName(key) : 'Senza materia'
    case 'docente':
      return key || 'Senza docente'
  }
}

export function useCategoryPins(): {
  pins: CategoryPins
  togglePin: (grouping: PinnableGrouping, key: string) => void
  unpinGroup: (grouping: PinnableGrouping) => void
} {
  const [pref, setPref] = usePreference<CategoryPins | undefined>(CATEGORY_PINS_PREF, undefined)
  const pins = useMemo(() => parseCategoryPins(pref), [pref])

  const togglePin = useCallback((grouping: PinnableGrouping, key: string) => {
    const next: CategoryPins = { ...pins }
    if (Object.hasOwn(next, grouping) && next[grouping] === key) {
      delete next[grouping]
    } else {
      next[grouping] = key
    }
    setPref(Object.keys(next).length > 0 ? next : undefined)
  }, [pins, setPref])

  const unpinGroup = useCallback((grouping: PinnableGrouping) => {
    if (!Object.hasOwn(pins, grouping)) return
    const next: CategoryPins = { ...pins }
    delete next[grouping]
    setPref(Object.keys(next).length > 0 ? next : undefined)
  }, [pins, setPref])

  return { pins, togglePin, unpinGroup }
}

export type SearchPin = { q: string; materia: string; stato: string }
export const SEARCH_PIN_KEY = 'rt.lessons.searchPin'

export function parseSearchPin(raw: unknown): SearchPin | null {
  try {
    let data = raw
    if (typeof raw === 'string') {
      data = JSON.parse(raw)
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null
    const obj = data as Partial<SearchPin>
    const q = typeof obj.q === 'string' ? obj.q.trim() : ''
    const materia = typeof obj.materia === 'string' ? obj.materia : ''
    const stato = typeof obj.stato === 'string' ? obj.stato : ''
    if (!q && !materia && !stato) return null
    return { q, materia, stato }
  } catch {
    return null
  }
}

export function sameSearchPin(a: SearchPin, b: SearchPin): boolean {
  return a.q.trim() === b.q.trim() && a.materia === b.materia && a.stato === b.stato
}

export function readSearchPin(): SearchPin | null {
  try {
    return parseSearchPin(sessionStorage.getItem(SEARCH_PIN_KEY))
  } catch {
    return null
  }
}

export function writeSearchPin(pin: SearchPin | null): void {
  try {
    if (pin) sessionStorage.setItem(SEARCH_PIN_KEY, JSON.stringify(pin))
    else sessionStorage.removeItem(SEARCH_PIN_KEY)
  } catch {
    /* sessionStorage non disponibile: vale solo in memoria per questa pagina */
  }
}

export function useSearchPin(): {
  searchPin: SearchPin | null
  pinSearch: (pin: SearchPin) => void
  unpinSearch: () => void
} {
  const [searchPin, setSearchPin] = useState<SearchPin | null>(() => readSearchPin())

  const pinSearch = useCallback((pin: SearchPin) => {
    const normalized = parseSearchPin(pin)
    if (!normalized) return
    writeSearchPin(normalized)
    setSearchPin(normalized)
  }, [])

  const unpinSearch = useCallback(() => {
    writeSearchPin(null)
    setSearchPin(null)
  }, [])

  return { searchPin, pinSearch, unpinSearch }
}

export type LessonsPrefs = { group: LessonsGrouping; sort: LessonsSort }
const DEFAULT_PREFS: LessonsPrefs = { group: 'data', sort: 'recenti' }
const STORAGE_KEY = 'rt-lessons-page'

export function parseLessonsPrefs(raw: string | null): LessonsPrefs {
  try {
    const data = (raw ? JSON.parse(raw) : {}) as Partial<LessonsPrefs>
    return {
      group: data.group && data.group in GROUPING_LABELS ? data.group : DEFAULT_PREFS.group,
      sort: data.sort && data.sort in SORT_OPTIONS ? data.sort : DEFAULT_PREFS.sort,
    }
  } catch {
    return DEFAULT_PREFS
  }
}

/** Raggruppamento e ordinamento scelti: preferenze del browser (non filtri nell'URL). */
export function useLessonsPrefs(): [LessonsPrefs, (patch: Partial<LessonsPrefs>) => void] {
  const [prefs, setPrefs] = useState(() => {
    try {
      return parseLessonsPrefs(localStorage.getItem(STORAGE_KEY))
    } catch {
      return DEFAULT_PREFS
    }
  })
  const update = useCallback((patch: Partial<LessonsPrefs>) => {
    setPrefs((current) => {
      const next = { ...current, ...patch }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        /* archiviazione non disponibile: vale solo per questa pagina */
      }
      return next
    })
  }, [])
  return [prefs, update]
}

/** Gruppi della pagina: dentro ogni gruppo l'ordine scelto; i giorni seguono la direzione della data. L'eventuale gruppo fissato sta sempre in cima. */
export function lessonsGroups(lessons: Lesson[], prefs: LessonsPrefs, now = new Date(), pinnedKey?: string): LessonGroup[] {
  let sorted = sortLessons(lessons, 'data', prefs.sort === 'meno-recenti' ? 'asc' : 'desc')
  if (prefs.sort === 'titolo') sorted = sortLessons(lessons, 'titolo', 'asc')
  else if (prefs.sort === 'studio-recente') {
    sorted.sort((a, b) => (Date.parse(b.study_last_at ?? '') || 0) - (Date.parse(a.study_last_at ?? '') || 0))
  } else if (prefs.sort === 'ricreate') {
    sorted.sort((a, b) => {
      const ta = a.pipeline_at ? Date.parse(a.pipeline_at) || 0 : 0
      const tb = b.pipeline_at ? Date.parse(b.pipeline_at) || 0 : 0
      if (ta && tb) {
        if (tb !== ta) return tb - ta
      } else if (ta && !tb) {
        return -1
      } else if (!ta && tb) {
        return 1
      }
      return (b.data || '').localeCompare(a.data || '') || (b.ora || '').localeCompare(a.ora || '') || b.folder_name.localeCompare(a.folder_name)
    })
  } else if (prefs.sort === 'piu-avanti' || prefs.sort === 'piu-indietro') {
    const direction = prefs.sort === 'piu-avanti' ? -1 : 1
    const ratio = (lesson: Lesson) => studyTotal(lesson) ? (lesson.study_learned ?? 0) / studyTotal(lesson) : 0
    sorted.sort((a, b) => direction * (ratio(a) - ratio(b) || (a.study_learning ?? 0) - (b.study_learning ?? 0)))
  }
  const dateDir = prefs.sort === 'meno-recenti' ? 'asc' : 'desc'
  const groups = groupLessons(sorted, prefs.group === 'data' ? 'giorno' : prefs.group, dateDir, now)
  if (prefs.group === 'nessuno' || pinnedKey === undefined) return groups
  const pinnedIndex = groups.findIndex((g) => g.key === pinnedKey)
  if (pinnedIndex <= 0) return groups
  return [groups[pinnedIndex], ...groups.slice(0, pinnedIndex), ...groups.slice(pinnedIndex + 1)]
}

function parseIso(date: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date.trim())
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
}

/** "2 ott" (con l'anno se non è quello corrente). */
export function shortDate(date: string, now = new Date()): string {
  const d = parseIso(date)
  if (!d) return date
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }) })
}

/** "giovedì 2 ottobre" (con l'anno se non è quello corrente). */
export function longDate(date: string, now = new Date()): string {
  const d = parseIso(date)
  if (!d) return date || '—'
  return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }) })
}

/** "FISIOLOGIA" → "Fisiologia", "PGSS" → "PGSS", "QA PROVA NOTTE" → "QA prova notte". */
export function subjectName(materia: string): string {
  if (!materia || materia !== materia.toLocaleUpperCase('it')) return materia
  const words = materia.split(/(\s+)/)
  return words
    .map((word, i) => {
      if (/^\s+$/.test(word)) return word
      if (word.length <= 4 && /^\p{Lu}+$/u.test(word)) {
        return word
      }
      const lower = word.toLocaleLowerCase('it')
      if (i === 0) {
        return lower.charAt(0).toLocaleUpperCase('it') + lower.slice(1)
      }
      return lower
    })
    .join('')
}

export function unitsText(lesson: Pick<Lesson, 'unit_count'>): string | null {
  return lesson.unit_count != null ? `${lesson.unit_count} unità` : null
}

/** Sottotitolo grigio della riga: i soli campi non già detti dal raggruppamento. */
export function lessonSubtitle(lesson: Lesson, group: LessonsGrouping, now = new Date()): string {
  const date = lesson.data ? shortDate(lesson.data, now) : null
  const subject = lesson.is_sample ? 'Esempio' : (lesson.materia ? subjectName(lesson.materia) : null)
  const teacher = lesson.is_sample ? null : (lesson.docente?.trim() || null)
  const fields =
    group === 'data'
      ? [subject, teacher]
      : group === 'mese'
        ? [date, subject, teacher]
        : group === 'materia'
          ? [date, lesson.is_sample ? subject : null, teacher]
          : group === 'docente'
            ? [date, subject]
            : [date, subject, teacher]
  const verified = lesson.phases?.review === 'VALID' && lesson.pending_issues === 0 ? 'Verificato' : null
  const media = (lesson.media_count ?? 0) > 0 ? `${lesson.media_count} media` : null
  return [
    ...fields,
    unitsText(lesson),
    lesson.recall_questions > 0 ? `${lesson.recall_questions} domande` : null,
    verified,
    media,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** Etichetta del gruppo: le materie come nel resto della pagina ("Fisiologia"). */
export function groupLabel(group: LessonGroup, grouping: LessonsGrouping): string {
  return grouping === 'materia' && group.key ? subjectName(group.label) : group.label
}

export type LessonStatus = 'in-corso' | 'da-verificare' | 'errore' | 'pronta' | 'da-completare'

export const STATUS_LABELS: Record<LessonStatus, string> = {
  'in-corso': 'In corso',
  'da-verificare': 'Da verificare',
  errore: 'Errore',
  pronta: 'Pronta',
  'da-completare': 'Da completare',
}

/** Il pallino della riga: in corso (un job attivo), errore, da verificare, pronta o da completare. */
export function lessonStatus(lesson: Lesson, running: boolean, failed = false): LessonStatus {
  if (running) return 'in-corso'
  if (failed || lesson.error || lesson.state === 'fallito') return 'errore'
  if (lesson.pending_issues > 0) return 'da-verificare'
  return lesson.phases.build === 'VALID' ? 'pronta' : 'da-completare'
}

/** Totali della selezione dai soli riepiloghi già caricati, senza mutare l'elenco. */
export function selectionDetails(lessons: readonly Lesson[]) {
  const sum = (values: (number | null | undefined)[]) => {
    const known = values.filter((value): value is number => value != null && Number.isFinite(value))
    return known.length ? known.reduce((total, value) => total + value, 0) : null
  }
  const dates = lessons.map(l => l.data).filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date)).sort()
  const duration = sum(lessons.map(l => l.duration_seconds))
  const cost = sum(lessons.map(l => l.cost_usd))
  const units = sum(lessons.map(l => l.unit_count))
  const learned = sum(lessons.map(l => l.study_learned)) ?? 0
  const ignored = sum(lessons.map(l => l.study_ignored)) ?? 0
  const learning = sum(lessons.map(l => l.study_learning)) ?? 0
  const latest = [...lessons].filter(l => l.study_last_at && Number.isFinite(Date.parse(l.study_last_at)))
    .sort((a, b) => Date.parse(b.study_last_at!) - Date.parse(a.study_last_at!))[0]
  const statuses = lessons.map(l => lessonStatus(l, false))
  const counts = (names: string[]) => {
    const values = new Map<string, number>()
    for (const name of names) values.set(name, (values.get(name) ?? 0) + 1)
    return [...values].map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name, 'it'))
  }
  return {
    count: lessons.length, duration, firstDate: dates[0] ?? null, lastDate: dates.at(-1) ?? null,
    units, learned, learning, ignored, studyUnits: units == null ? null : Math.max(0, units - ignored), questions: sum(lessons.map(l => l.recall_questions)), pending: sum(lessons.map(l => l.recall_pending)),
    cost, costPerHour: cost != null && duration && duration > 0 ? cost * 3600 / duration : null,
    lastStudy: latest ? { at: latest.study_last_at!, lesson: lessonTitle(latest) } : null,
    ready: statuses.filter(status => status === 'pronta').length,
    toVerify: statuses.filter(status => status === 'da-verificare').length,
    errors: statuses.filter(status => status === 'errore').length,
    percentages: {
      learned: units ? learned / units * 100 : 0,
      learning: units ? learning / units * 100 : 0,
      ignored: units ? ignored / units * 100 : 0,
      toLearn: units ? Math.max(0, units - learned - learning - ignored) / units * 100 : 0,
    },
    subjects: counts(lessons.filter(l => !l.is_sample).map(l => subjectName(l.materia.trim()) || 'Senza materia')),
    teachers: counts(lessons.filter(l => !l.is_sample).map(l => l.docente.trim() || 'Senza docente')),
  }
}

/** Denominatore comune per l'avanzamento: le unità della scaletta senza le ignorate. */
export function studyTotal(lesson: Pick<Lesson, 'unit_count' | 'study_ignored'>): number {
  return Math.max(0, (lesson.unit_count ?? 0) - (lesson.study_ignored ?? 0))
}

export type SelectionSort = 'lezione' | 'audio' | 'studio' | 'domande' | 'costo'

/** Colonne del popup: valori sconosciuti in fondo, in entrambe le direzioni. */
export function sortSelection(lessons: readonly Lesson[], key: SelectionSort, direction: 'asc' | 'desc'): Lesson[] {
  const value = (lesson: Lesson) => {
    if (key === 'lezione') return lessonTitle(lesson)
    if (key === 'audio') return lesson.duration_seconds
    if (key === 'studio') return studyTotal(lesson) ? (lesson.study_learned ?? 0) / studyTotal(lesson) : 0
    if (key === 'domande') return lesson.recall_questions
    return lesson.cost_usd
  }
  return [...lessons].sort((a, b) => {
    const first = value(a), second = value(b)
    if (first == null || second == null) return first == null ? second == null ? 0 : 1 : -1
    const comparison = typeof first === 'string' && typeof second === 'string'
      ? first.localeCompare(second, 'it', { numeric: true, sensitivity: 'base' }) : Number(first) - Number(second)
    return (direction === 'asc' ? 1 : -1) * comparison || lessonTitle(a).localeCompare(lessonTitle(b), 'it')
  })
}

/** "52 min", "1 h 05 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '—'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${Math.max(1, minutes)} min`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`
}

/** Righe del popup Info: tutto ciò che sulla riga è eliso. */
export function lessonInfo(lesson: Lesson, running: boolean, now = new Date()): [string, string][] {
  const state = lesson.state ? (STATE_LABELS[lesson.state] ?? lesson.state).toLocaleLowerCase('it') : null
  const status = [
    running ? 'in corso' : state,
    lesson.pending_issues > 0 ? `${lesson.pending_issues} da verificare` : null,
    lesson.error ? `errore: ${lesson.error}` : null,
  ].filter(Boolean).join(' · ')
  return [
    ['Materia', lesson.is_sample ? 'Esempio' : (lesson.materia ? subjectName(lesson.materia) : '—')],
    ['Docente', lesson.is_sample ? '—' : (lesson.docente?.trim() || '—')],
    ['Data', longDate(lesson.data, now)],
    ['Durata', formatDuration(lesson.duration_seconds)],
    ['Unità', lesson.unit_count != null ? String(lesson.unit_count) : '—'],
    ['Domande', `${lesson.recall_questions} nel pool · ${lesson.recall_pending} da fare`],
    ['Costo', formatCost(lesson.cost_usd)],
    ['Stato', status || '—'],
  ]
}

/** Perché il Markdown di alcune lezioni selezionate non si scarica (il download in blocco usa solo i documenti finali). */
export function markdownExportNote(lessons: Lesson[]): { unavailable: string | null; hint: string | null } {
  if (lessons.length === 0) return { unavailable: 'nessuna lezione selezionata', hint: null }
  const missing = lessons.filter((l) => l.phases.build !== 'VALID')
  if (missing.length === 0) return { unavailable: null, hint: null }
  const why = 'il Markdown in blocco usa il documento finale, che manca o non è aggiornato (fase Documento)'
  if (missing.length === lessons.length) {
    return { unavailable: lessons.length === 1 ? `${why}; dalla pagina della lezione si scarica l'anteprima` : `nessuna lezione selezionata ha il documento finale: ${why}`, hint: null }
  }
  return { unavailable: null, hint: `${lessons.length - missing.length} di ${lessons.length}: ${missing.map(lessonTitle).join(', ')} senza documento finale` }
}

/**
 * Filtra le ore mancanti del calendario per la chiave del gruppo:
 * - 'materia': le ore mancanti di quella materia
 * - 'data': le ore mancanti di quel giorno (YYYY-MM-DD)
 * - 'mese': le ore mancanti di quel mese (YYYY-MM)
 * - 'docente': le ore mancanti con quel docente
 * - 'nessuno': nessuna (vuoto)
 */
export function filterMissingLessons(
  missingData: CalendarMissingLessons | undefined | null,
  grouping: LessonsGrouping,
  groupKey: string,
): CalendarToRecoverItem[] {
  if (grouping === 'nessuno' || !missingData?.subjects) return []
  const normKey = groupKey.trim()

  if (grouping === 'materia') {
    const match = missingData.subjects.find(
      (s) => (s.materia ?? '').trim().toUpperCase() === normKey.toUpperCase(),
    )
    const materia = match?.materia ?? ''
    return (match?.missing ?? []).map((m) => ({ ...m, materia: m.materia || materia }))
  }

  // Le materie arrivano una dopo l'altra: fuori dal raggruppamento per materia si torna all'ordine del calendario.
  const allItems = missingData.subjects
    .flatMap((s) => (s.missing ?? []).map((m) => ({ ...m, materia: m.materia || s.materia })))
    .sort((a, b) => a.date.localeCompare(b.date) || a.start_time.localeCompare(b.start_time))

  switch (grouping) {
    case 'data':
      return allItems.filter((item) => item?.date === normKey)
    case 'mese':
      return allItems.filter((item) => (item?.date ?? '').slice(0, 7) === normKey)
    case 'docente':
      return allItems.filter(
        (item) => (item?.docente ?? '').trim().toLowerCase() === normKey.toLowerCase(),
      )
    default:
      return []
  }
}
