import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import type { Lesson } from './format'
import { filterLessons, type LessonListFilters } from './lessonSearch'

/**
 * Filtri nell'URL (?q=&materia=&stato=), così restano dopo la ricarica e si condividono. Il
 * testo vive anche in uno stato locale: l'URL si aggiorna in modo asincrono e un campo legato
 * solo a lui perderebbe i tasti premuti in fretta.
 */
export function useLessonFilters(): [
  LessonListFilters,
  (key: keyof LessonListFilters, value: string) => void,
  () => void,
  (values: Partial<{ q: string; materia: string; stato: string }>) => void,
] {
  const [params, setParams] = useSearchParams()
  const urlQ = params.get('q') ?? ''
  const [q, setQ] = useState(urlQ)
  // Testi scritti nell'URL e non ancora arrivati: quando arrivano non toccano il campo.
  const pending = useRef<string[]>([])
  useEffect(() => {
    const index = pending.current.indexOf(urlQ)
    if (index >= 0) pending.current.splice(0, index + 1)
    else {
      // Cambiato da fuori (indietro nel browser, link): l'URL vince.
      pending.current = []
      setQ(urlQ)
    }
  }, [urlQ])

  function setFilter(key: keyof LessonListFilters, value: string) {
    if (key === 'q') {
      setQ(value)
      pending.current.push(value)
    }
    const name = key === 'state' ? 'stato' : key
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(name, value)
        else next.delete(name)
        return next
      },
      { replace: true },
    )
  }
  // Un solo aggiornamento dell'URL: più setParams nello stesso istante si sovrascrivono.
  function resetFilters() {
    setQ('')
    pending.current.push('')
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const name of ['q', 'materia', 'stato']) next.delete(name)
        return next
      },
      { replace: true },
    )
  }
  function applyFilters(values: Partial<{ q: string; materia: string; stato: string }>) {
    if (values.q !== undefined) {
      setQ(values.q)
      pending.current.push(values.q)
    }
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (values.q !== undefined) {
          if (values.q) next.set('q', values.q)
          else next.delete('q')
        }
        if (values.materia !== undefined) {
          if (values.materia) next.set('materia', values.materia)
          else next.delete('materia')
        }
        if (values.stato !== undefined) {
          if (values.stato) next.set('stato', values.stato)
          else next.delete('stato')
        }
        return next
      },
      { replace: true },
    )
  }
  return [{ q, materia: params.get('materia') ?? '', state: params.get('stato') ?? '' }, setFilter, resetFilters, applyFilters]
}

/** Elenco filtrato lato client: il filtro non chiama l'API a ogni tasto. */
export function useFilteredLessons(lessons: Lesson[] | undefined) {
  const [filters, setFilter, resetFilters, applyFilters] = useLessonFilters()
  return { filters, setFilter, resetFilters, applyFilters, filtered: filterLessons(lessons ?? [], filters) }
}
