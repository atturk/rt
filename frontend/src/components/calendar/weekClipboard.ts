import { useSyncExternalStore } from 'react'
import type { CalendarPasteEntry, CalendarWeekView } from '@/api/calendar'

type WeekClipboard = { sourceStart: string; entries: CalendarPasteEntry[] }
const KEY = 'rt:calendar-clipboard'
const listeners = new Set<() => void>()
function read(): WeekClipboard | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(KEY) ?? 'null') as WeekClipboard | null
    return value && typeof value.sourceStart === 'string' && Array.isArray(value.entries) ? value : null
  } catch { return null }
}
let snapshot = read()
export function copyWeek(week: CalendarWeekView) {
  snapshot = { sourceStart: week.start_date, entries: week.days.flatMap(day => (day.events ?? []).map(event => ({
    day_of_week: event.day_of_week, start_time: event.start_time, end_time: event.end_time, materia: event.materia, docente: event.docente,
  }))) }
  try { sessionStorage.setItem(KEY, JSON.stringify(snapshot)) } catch { /* La copia resta negli appunti della pagina. */ }
  listeners.forEach(listener => listener())
}
export function useWeekClipboard() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => snapshot)
}
