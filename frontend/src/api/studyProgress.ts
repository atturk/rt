import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { recallKeys, type StudyLesson } from './recall'

export type StudyStatus = Schemas['StudyStatusUpdate']['status']

/** Attesa dopo l'ultimo cambio di stato prima di salvarlo: si può ciclare fra gli stati senza aspettare il server. */
export const STUDY_STATUS_SAVE_DELAY = 700

type PendingStatus = { lessonId: number; status: StudyStatus; saved: StudyLesson['units'][number] | undefined; timer: ReturnType<typeof setTimeout> }

/** Lo stato cambia subito nello Studio; al server va solo l'ultimo, quando i tasti si fermano. */
export function useStudyStatus(lessonId: number) {
  const client = useQueryClient()
  const pending = useRef(new Map<string, PendingStatus>())
  const inFlight = useRef(0)
  const [error, setError] = useState<unknown>(null)

  const save = useCallback((unitId: string) => {
    const entry = pending.current.get(unitId)
    if (!entry) return
    clearTimeout(entry.timer)
    pending.current.delete(unitId)
    const key = recallKeys.study(entry.lessonId)
    const refresh = () => {
      if (pending.current.size || inFlight.current) return
      void client.invalidateQueries({ queryKey: key })
      void client.invalidateQueries({ queryKey: ['lessons'] })
    }
    // Tornati allo stato di partenza: non c'è niente da salvare.
    if (entry.saved?.status === entry.status) return refresh()
    inFlight.current += 1
    unwrap(api.PUT(
      '/api/v1/lessons/{lesson_id}/study/units/{unit_id}',
      // keepalive: il salvataggio arriva anche se la finestra si chiude subito dopo.
      { params: { path: { lesson_id: entry.lessonId, unit_id: unitId } }, body: { status: entry.status }, keepalive: true },
    )).then(() => setError(null), failure => {
      setError(failure)
      if (pending.current.has(unitId) || !entry.saved) return
      client.setQueryData<StudyLesson>(key, old => old && ({ ...old, units: old.units.map(unit => unit.id === unitId ? entry.saved! : unit) }))
    }).finally(() => {
      inFlight.current -= 1
      refresh()
    })
  }, [client])

  // Uscendo dallo Studio, ricaricando o chiudendo la finestra si salva subito quello che aspettava.
  useEffect(() => {
    const map = pending.current
    const flush = () => { [...map.keys()].forEach(save) }
    window.addEventListener('pagehide', flush)
    return () => { window.removeEventListener('pagehide', flush); flush() }
  }, [save])

  const mutate = useCallback(({ unitId, status }: { unitId: string; status: StudyStatus }) => {
    const key = recallKeys.study(lessonId)
    void client.cancelQueries({ queryKey: key })
    const previous = pending.current.get(unitId)
    if (previous) clearTimeout(previous.timer)
    const saved = previous ? previous.saved : client.getQueryData<StudyLesson>(key)?.units.find(unit => unit.id === unitId)
    client.setQueryData<StudyLesson>(key, old => old && ({ ...old, units: old.units.map(unit =>
      unit.id === unitId ? { ...unit, status, status_at: new Date().toISOString() } : unit) }))
    pending.current.set(unitId, { lessonId, status, saved, timer: setTimeout(() => save(unitId), STUDY_STATUS_SAVE_DELAY) })
  }, [client, lessonId, save])

  return { mutate, isError: error !== null, error }
}

export function useStudyRead(lessonId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (unitId: string) => unwrap(api.POST(
      '/api/v1/lessons/{lesson_id}/study/units/{unit_id}/read',
      { params: { path: { lesson_id: lessonId, unit_id: unitId } } },
    )),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: recallKeys.study(lessonId) }),
      client.invalidateQueries({ queryKey: ['lessons'] }),
    ]),
  })
}
