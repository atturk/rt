import { describe, expect, it } from 'vitest'
import { isoWeek, selectWeekRange, shiftWeekDate, weekMonday, weekOccupancy, weekRangeLabel, yearWeeks } from './weekRange'

it('rispetta gli anni ISO con 52 o 53 settimane e il cambio di anno', () => {
  expect(yearWeeks(2025)).toHaveLength(52)
  expect(yearWeeks(2026)).toHaveLength(53)
  expect(yearWeeks(2026)[0]).toBe('2025-12-29')
  expect(yearWeeks(2026).at(-1)).toBe('2026-12-28')
  expect(isoWeek('2027-01-01')).toEqual({ year: 2026, number: 53 })
  expect(weekMonday('2026-10-25')).toBe('2026-10-19')
  expect(shiftWeekDate('2026-10-19', 7)).toBe('2026-10-26')
})
it('scambia i clic inversi, include tutta la settimana finale e distingue anni diversi', () => {
  expect(selectWeekRange('2026-10-19', '2026-10-12')).toEqual({ from: '2026-10-12', to: '2026-10-26' })
  expect(weekRangeLabel(selectWeekRange('2026-12-28', '2027-01-04'))).toBe('Settimane 53 (2026)–1 (2027)')
})
describe('occupazione', () => {
  const entries = [{ id: 2, valid_from: '2026-10-12', valid_to: '2026-10-26', day_of_week: 0, start_time: '09:00', end_time: '10:30', materia: 'Analisi' }, { id: 1, valid_from: '2026-10-12', day_of_week: 1, start_time: '09:00', end_time: '11:00', materia: 'Fisica' }]
  it('somma le ore e confronta l’orario, con la fine esclusa', () => {
    expect(weekOccupancy(entries, '2026-10-05')).toEqual({ hours: 0, fingerprint: '' })
    expect(weekOccupancy(entries, '2026-10-12')).toEqual({ hours: 3.5, fingerprint: '0:09:00:10:30:analisi:|1:09:00:11:00:fisica:' })
    expect(weekOccupancy(entries.toReversed(), '2026-10-12')).toEqual({ hours: 3.5, fingerprint: '0:09:00:10:30:analisi:|1:09:00:11:00:fisica:' })
    expect(weekOccupancy(entries.map(entry => ({ ...entry, id: entry.id + 10 })), '2026-10-12')).toEqual(weekOccupancy(entries, '2026-10-12'))
    expect(weekOccupancy(entries, '2026-10-26')).toEqual({ hours: 2, fingerprint: '1:09:00:11:00:fisica:' })
  })
})
