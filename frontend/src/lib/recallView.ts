import { useCallback, useEffect, useState } from 'react'

import type { LessonRecallStats } from '@/api/recall'
import type { Lesson } from './format'
import { groupLessons, sortLessons, type LessonGroup, type LessonViewMode, type SortDir } from './lessonView'
import { countStatus } from './recall'

/**
 * Come si guarda la pagina del recall: lezioni raggruppate per materia (predefinito) o per
 * giorno, in schede o in tabella, ordinate per data, titolo o domande da porre. Come per la
 * pagina Lezioni sono preferenze del browser (localStorage), non filtri nell'URL.
 */
export type RecallSortKey = 'data' | 'titolo' | 'domande'
export type RecallGroupBy = 'materia' | 'giorno'

export type RecallViewPrefs = {
  view: LessonViewMode
  sort: RecallSortKey
  dir: SortDir
  group: RecallGroupBy
  /** Gruppi chiusi, come `materia:<nome>` o `giorno:<data>`. */
  collapsed: string[]
}

export const DEFAULT_RECALL_PREFS: RecallViewPrefs = { view: 'schede', sort: 'data', dir: 'desc', group: 'materia', collapsed: [] }

export const RECALL_GROUP_LABELS: Record<RecallGroupBy, string> = { materia: 'Materia', giorno: 'Giorno' }

export const RECALL_SORT_LABELS: Record<RecallSortKey, string> = {
  data: 'Data',
  titolo: 'Titolo',
  domande: 'Domande da porre',
}

export const RECALL_DEFAULT_DIR: Record<RecallSortKey, SortDir> = { data: 'desc', titolo: 'asc', domande: 'desc' }

export const pendingOf = (stats?: LessonRecallStats) => countStatus(stats?.questions, 'pending')

/** Lezioni ordinate e raggruppate per materia (alfabetico, "Senza materia" in fondo) o per
 * giorno (nella direzione della data, "Senza data" in fondo). */
export function groupForRecall(lessons: Lesson[], stats: Map<number, LessonRecallStats>,
  prefs: Pick<RecallViewPrefs, 'sort' | 'dir'> & Partial<Pick<RecallViewPrefs, 'group'>>): LessonGroup[] {
  let sorted: Lesson[]
  if (prefs.sort === 'domande') {
    const sign = prefs.dir === 'asc' ? 1 : -1
    const byDate = sortLessons(lessons, 'data', 'desc')
    sorted = [...byDate].sort((a, b) => sign * (pendingOf(stats.get(a.id)) - pendingOf(stats.get(b.id))))
  } else {
    sorted = sortLessons(lessons, prefs.sort, prefs.dir)
  }
  const group = prefs.group ?? 'materia'
  return groupLessons(sorted, group, prefs.sort === 'data' ? prefs.dir : 'desc')
}

/** Totali di una materia: lezioni pronte, domande da porre, risposte date. */
export function subjectTotals(lessons: Lesson[], stats: Map<number, LessonRecallStats>) {
  const items = lessons.map((l) => stats.get(l.id))
  return {
    ready: items.filter((s) => s?.ready).length,
    pending: items.reduce((sum, s) => sum + pendingOf(s), 0),
    answers: items.reduce((sum, s) => sum + (s?.answers ?? 0), 0),
  }
}

export const subjectPath = (materia: string) => `/recall/materie/${encodeURIComponent(materia)}`
/** Recall del giorno: la sessione per materia sulle lezioni di una data (materia GIORNO:<data>). */
export const dayPath = (day: string) => `/recall/giorno/${encodeURIComponent(day)}`
export const daySubject = (day: string) => `GIORNO:${day}`

const STORAGE_KEY = 'rt-recall-view'

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

export function parseRecallPrefs(raw: string | null): RecallViewPrefs {
  let data: Record<string, unknown> = {}
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>
  } catch {
    /* preferenze illeggibili: si riparte da quelle predefinite */
  }
  const d = DEFAULT_RECALL_PREFS
  return {
    view: pick(data.view, ['schede', 'tabella'], d.view),
    sort: pick(data.sort, Object.keys(RECALL_SORT_LABELS) as RecallSortKey[], d.sort),
    dir: pick(data.dir, ['asc', 'desc'], d.dir),
    group: pick(data.group, Object.keys(RECALL_GROUP_LABELS) as RecallGroupBy[], d.group),
    collapsed: Array.isArray(data.collapsed) ? data.collapsed.filter((c): c is string => typeof c === 'string').slice(-200) : [],
  }
}

function load(): RecallViewPrefs {
  try {
    return parseRecallPrefs(localStorage.getItem(STORAGE_KEY))
  } catch {
    return DEFAULT_RECALL_PREFS
  }
}

export function useRecallViewPrefs() {
  const [prefs, setPrefs] = useState(load)
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }, [prefs])
  const update = useCallback((patch: Partial<RecallViewPrefs>) => setPrefs((p) => ({ ...p, ...patch })), [])
  const sortBy = useCallback(
    (key: RecallSortKey) =>
      setPrefs((p) => ({ ...p, sort: key, dir: p.sort === key ? (p.dir === 'asc' ? 'desc' : 'asc') : RECALL_DEFAULT_DIR[key] })),
    [],
  )
  const toggleGroup = useCallback(
    (id: string) =>
      setPrefs((p) => ({ ...p, collapsed: p.collapsed.includes(id) ? p.collapsed.filter((c) => c !== id) : [...p.collapsed, id] })),
    [],
  )
  return { prefs, update, sortBy, toggleGroup }
}
