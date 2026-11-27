import type { CalendarTemplateEntryView } from '@/api/calendar'

export type WeekRange = { from: string; to: string }
const DAY = 86_400_000
// Calcoli in UTC su sole date, indipendenti da ora legale e fuso del browser.
function date(iso: string) { return new Date(`${iso}T00:00:00Z`) }
function iso(value: Date) { return value.toISOString().slice(0, 10) }
export function shiftWeekDate(value: string, days: number): string {
  return iso(new Date(date(value).getTime() + days * DAY))
}
export function weekMonday(value: string): string {
  const d = date(value)
  return shiftWeekDate(value, -((d.getUTCDay() + 6) % 7))
}
export function isoWeek(value: string): { year: number; number: number } {
  const thursday = date(shiftWeekDate(weekMonday(value), 3))
  const year = thursday.getUTCFullYear()
  const first = weekMonday(`${year}-01-04`)
  return { year, number: Math.round((date(weekMonday(value)).getTime() - date(first).getTime()) / (7 * DAY)) + 1 }
}
export function yearWeeks(year: number): string[] {
  const start = weekMonday(`${year}-01-04`)
  const count = isoWeek(`${year}-12-28`).number
  return Array.from({ length: count }, (_, i) => shiftWeekDate(start, 7 * i))
}
export function selectWeekRange(first: string, last: string): WeekRange {
  const [from, end] = [first, last].sort()
  return { from, to: shiftWeekDate(end, 7) }
}
export function weekRangeLabel(range: WeekRange): string {
  const first = isoWeek(range.from), last = isoWeek(shiftWeekDate(range.to, -7))
  return first.year === last.year ? `Settimane ${first.number}–${last.number}` : `Settimane ${first.number} (${first.year})–${last.number} (${last.year})`
}
export function weekRangesLabel(ranges: readonly WeekRange[]): string {
  return ranges.map(weekRangeLabel).join(', ')
}
export function rangeBetween(a: string, b: string): string[] {
  const [from, to] = [a, b].sort()
  const weeks: string[] = []
  for (let week = from; week <= to; week = shiftWeekDate(week, 7)) weeks.push(week)
  return weeks
}
export function toggleWeek(selected: ReadonlySet<string>, week: string): Set<string> {
  const next = new Set(selected)
  if (next.has(week)) next.delete(week)
  else next.add(week)
  return next
}
export function contiguousRuns(selected: Iterable<string>): WeekRange[] {
  const sorted = [...new Set(selected)].sort()
  if (!sorted.length) return []
  const runs: WeekRange[] = []
  let from = sorted[0], prev = sorted[0]
  for (let i = 1; i < sorted.length; i++) {
    const week = sorted[i]
    if (shiftWeekDate(prev, 7) === week) { prev = week; continue }
    runs.push({ from, to: shiftWeekDate(prev, 7) })
    from = prev = week
  }
  runs.push({ from, to: shiftWeekDate(prev, 7) })
  return runs
}
export function expandWeekRanges(initial?: WeekRange | readonly WeekRange[] | null): string[] {
  if (!initial) return []
  const ranges = Array.isArray(initial) ? initial : [initial]
  const weeks = new Set<string>()
  for (const range of ranges) {
    for (let week = range.from; week < range.to; week = shiftWeekDate(week, 7)) weeks.add(week)
  }
  return [...weeks].sort()
}
export function weekOccupancy(entries: CalendarTemplateEntryView[], monday: string) {
  const valid = entries.filter(e => { const day = shiftWeekDate(monday, e.day_of_week); return e.valid_from <= day && (!e.valid_to || day < e.valid_to) })
  const hours = valid.reduce((n, e) => {
    const hour = (v: string) => { const [h, m] = v.split(':').map(Number); return h + m / 60 }
    return n + hour(e.end_time) - hour(e.start_time)
  }, 0)
  return { hours, fingerprint: valid.map(e => [e.day_of_week, e.start_time, e.end_time, e.materia.toLocaleLowerCase(), e.docente ?? ''].join(':')).sort().join('|') }
}
export function weekDateLabel(value: string): string {
  return date(value).toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function academicYear(value: string): number {
  const thursday = date(shiftWeekDate(weekMonday(value), 3))
  return thursday.getUTCFullYear() - (thursday.getUTCMonth() < 8 ? 1 : 0)
}
export function academicWeeks(year: number): string[] {
  const start = weekMonday(`${year}-09-04`), end = weekMonday(`${year + 1}-09-04`)
  const weeks: string[] = []
  for (let week = start; week < end; week = shiftWeekDate(week, 7)) weeks.push(week)
  return weeks
}
export function weekMonth(monday: string): string { return shiftWeekDate(monday, 3).slice(0, 7) }
export function weekTitle(monday: string, hours: number, changed = false): string {
  const short = (value: string) => date(value).toLocaleDateString('it-IT', { day: 'numeric', month: 'short', timeZone: 'UTC' })
  return `Settimana ${isoWeek(monday).number} · ${short(monday)}–${short(shiftWeekDate(monday, 4))} ${monday.slice(0, 4)} · ${hours.toLocaleString('it-IT')} ore${changed ? ' · l’orario cambia da qui' : ''}`
}
