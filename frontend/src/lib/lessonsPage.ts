import { useCallback, useState } from 'react'

import { STATE_LABELS, formatCost, lessonTitle, type Lesson } from './format'
import { groupLessons, sortLessons, type LessonGroup } from './lessonView'

/**
 * Pagina Lezioni del design 4.2 (schermate 01, 01b, 01c, 04): elenco a righe raggruppato per
 * data, materia o docente. Sotto il titolo solo i campi che il gruppo non dice già; il resto
 * sta nel popup Info.
 */
export type LessonsGrouping = 'data' | 'mese' | 'materia' | 'docente'
export type LessonsSort = 'recenti' | 'meno-recenti' | 'titolo' | 'studio-recente' | 'piu-avanti' | 'piu-indietro'

export const GROUPING_LABELS: Record<LessonsGrouping, string> = { data: 'Per data', mese: 'Per mese', materia: 'Per materia', docente: 'Per docente' }
export const GROUP_CYCLE: LessonsGrouping[] = ['data', 'mese', 'materia', 'docente']
export const PHONE_GROUP_LABELS: Record<LessonsGrouping, string> = { data: 'Data', mese: 'Mese', materia: 'Materia', docente: 'Docente' }

export const SORT_OPTIONS: Record<LessonsSort, string> = {
  recenti: 'Dalla più recente',
  'meno-recenti': 'Dalla meno recente',
  titolo: 'Per titolo',
  'studio-recente': 'Studiate di recente',
  'piu-avanti': 'Più avanti nello studio',
  'piu-indietro': 'Più indietro nello studio',
}
export const SORT_CYCLE: LessonsSort[] = ['recenti', 'meno-recenti', 'titolo', 'studio-recente', 'piu-avanti', 'piu-indietro']
export const PHONE_SORT_LABELS: Record<LessonsSort, string> = {
  recenti: 'Recenti', 'meno-recenti': 'Vecchie', titolo: 'A–Z',
  'studio-recente': 'Studio', 'piu-avanti': 'Avanti', 'piu-indietro': 'Indietro',
}

/** Sfondo del gruppo n-esimo secondo la preferenza (variabili --group-* in index.css). */
export function groupBackground(index: number, mode: string | undefined): string | undefined {
  if (mode === 'niente') return undefined
  if (mode === 'grigi') return 'var(--group-gray)'
  return `var(--group-${(index % 4) + 1})`
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

/** Gruppi della pagina: dentro ogni gruppo l'ordine scelto; i giorni seguono la direzione della data. */
export function lessonsGroups(lessons: Lesson[], prefs: LessonsPrefs, now = new Date()): LessonGroup[] {
  let sorted = sortLessons(lessons, 'data', prefs.sort === 'meno-recenti' ? 'asc' : 'desc')
  if (prefs.sort === 'titolo') sorted = sortLessons(lessons, 'titolo', 'asc')
  else if (prefs.sort === 'studio-recente') {
    sorted.sort((a, b) => (Date.parse(b.study_last_at ?? '') || 0) - (Date.parse(a.study_last_at ?? '') || 0))
  } else if (prefs.sort === 'piu-avanti' || prefs.sort === 'piu-indietro') {
    const direction = prefs.sort === 'piu-avanti' ? -1 : 1
    const ratio = (lesson: Lesson) => lesson.unit_count ? (lesson.study_learned ?? 0) / lesson.unit_count : 0
    sorted.sort((a, b) => direction * (ratio(a) - ratio(b) || (a.study_learning ?? 0) - (b.study_learning ?? 0)))
  }
  const dateDir = prefs.sort === 'meno-recenti' ? 'asc' : 'desc'
  return groupLessons(sorted, prefs.group === 'data' ? 'giorno' : prefs.group, dateDir, now)
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

/** "FISIOLOGIA" → "Fisiologia": le materie arrivano in maiuscolo dall'API. */
export function subjectName(materia: string): string {
  if (!materia || materia !== materia.toLocaleUpperCase('it')) return materia
  const lower = materia.toLocaleLowerCase('it')
  return lower.charAt(0).toLocaleUpperCase('it') + lower.slice(1)
}

export function unitsText(lesson: Pick<Lesson, 'unit_count'>): string | null {
  return lesson.unit_count != null ? `${lesson.unit_count} unità` : null
}

/** Sottotitolo grigio della riga: i soli campi non già detti dal raggruppamento. */
export function lessonSubtitle(lesson: Lesson, group: LessonsGrouping, now = new Date()): string {
  const date = lesson.data ? shortDate(lesson.data, now) : null
  const subject = lesson.materia ? subjectName(lesson.materia) : null
  const teacher = lesson.docente?.trim() || null
  const fields =
    group === 'data'
      ? [subject, teacher]
      : group === 'mese'
        ? [date, subject, teacher]
        : group === 'materia'
          ? [date, teacher]
          : [date, subject]
  return [...fields, unitsText(lesson), lesson.study_learned > 0 ? `${lesson.study_learned} apprese` : null].filter(Boolean).join(' · ')
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
export function lessonStatus(lesson: Lesson, running: boolean): LessonStatus {
  if (running) return 'in-corso'
  if (lesson.error || lesson.state === 'fallito') return 'errore'
  if (lesson.pending_issues > 0) return 'da-verificare'
  return lesson.phases.build === 'VALID' ? 'pronta' : 'da-completare'
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
    ['Materia', lesson.materia ? subjectName(lesson.materia) : '—'],
    ['Docente', lesson.docente?.trim() || '—'],
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
