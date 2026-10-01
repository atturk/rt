import { useCallback, useEffect, useState } from 'react'

import type { LessonViewMode, SortDir } from './lessonView'

/**
 * Preferenze di vista di un elenco di lezioni (schede o tabella, ordinamento, raggruppamento,
 * gruppi chiusi), salvate nel browser con una chiave per pagina. Come per la dashboard sono
 * preferenze, non filtri: restano in localStorage e non nell'URL.
 */
export type ViewPrefs<S extends string, G extends string> = {
  view: LessonViewMode
  sort: S
  dir: SortDir
  group: G
  /** Gruppi chiusi, come `<raggruppamento>:<chiave>`. */
  collapsed: string[]
}

export type ViewPrefsSpec<S extends string, G extends string> = {
  sorts: readonly S[]
  groups: readonly G[]
  defaults: ViewPrefs<S, G>
  /** Direzione naturale al primo clic su una colonna. */
  defaultDir: Record<S, SortDir>
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

export function parsePrefs<S extends string, G extends string>(raw: string | null, spec: ViewPrefsSpec<S, G>): ViewPrefs<S, G> {
  let data: Record<string, unknown> = {}
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>
  } catch {
    /* preferenze illeggibili: si riparte da quelle predefinite */
  }
  const d = spec.defaults
  return {
    view: pick(data.view, ['schede', 'tabella'], d.view),
    sort: pick(data.sort, spec.sorts, d.sort),
    dir: pick(data.dir, ['asc', 'desc'], d.dir),
    group: pick(data.group, spec.groups, d.group),
    collapsed: Array.isArray(data.collapsed) ? data.collapsed.filter((c): c is string => typeof c === 'string').slice(-200) : [],
  }
}

export function useViewPrefs<S extends string, G extends string>(storageKey: string, spec: ViewPrefsSpec<S, G>) {
  const [prefs, setPrefs] = useState(() => {
    try {
      return parsePrefs(localStorage.getItem(storageKey), spec)
    } catch {
      return spec.defaults
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(prefs))
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }, [prefs, storageKey])
  const update = useCallback((patch: Partial<ViewPrefs<S, G>>) => setPrefs((p) => ({ ...p, ...patch })), [])
  const { defaultDir } = spec
  /** Clic su un'intestazione di colonna: stessa colonna inverte, nuova colonna parte dalla direzione naturale. */
  const sortBy = useCallback(
    (key: S) => setPrefs((p) => ({ ...p, sort: key, dir: p.sort === key ? (p.dir === 'asc' ? 'desc' : 'asc') : defaultDir[key] })),
    [defaultDir],
  )
  const toggleGroup = useCallback(
    (id: string) =>
      setPrefs((p) => ({ ...p, collapsed: p.collapsed.includes(id) ? p.collapsed.filter((c) => c !== id) : [...p.collapsed, id] })),
    [],
  )
  return { prefs, update, sortBy, toggleGroup }
}
