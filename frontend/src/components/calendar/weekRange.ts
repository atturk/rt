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
export function weekOccupancy(entries: CalendarTemplateEntryView[], monday: string) {
  const valid = entries.filter(e => e.valid_from <= monday && (!e.valid_to || monday < e.valid_to))
  const hours = valid.reduce((n, e) => {
    const hour = (v: string) => { const [h, m] = v.split(':').map(Number); return h + m / 60 }
    return n + hour(e.end_time) - hour(e.start_time)
  }, 0)
  return { hours, fingerprint: valid.map(e => e.id).sort((a, b) => a - b).join(',') }
}
export function weekDateLabel(value: string): string {
  return date(value).toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}
