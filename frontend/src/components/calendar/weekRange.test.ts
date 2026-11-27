import { describe, expect, it } from 'vitest'
import {
  contiguousRuns,
  expandWeekRanges,
  isoWeek,
  rangeBetween,
  selectWeekRange,
  shiftWeekDate,
  toggleWeek,
  weekMonday,
  weekOccupancy,
  weekRangeLabel,
  weekRangesLabel,
  yearWeeks,
} from './weekRange'

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
describe('selezione multipla', () => {
  it('rangeBetween include gli estremi in entrambe le direzioni', () => {
    expect(rangeBetween('2026-10-12', '2026-10-12')).toEqual(['2026-10-12'])
    expect(rangeBetween('2026-10-26', '2026-10-12')).toEqual(['2026-10-12', '2026-10-19', '2026-10-26'])
  })
  it('toggleWeek aggiunge e toglie senza mutare il Set originale', () => {
    const initial = new Set(['2026-10-12'])
    const added = toggleWeek(initial, '2026-10-26')
    expect([...added]).toEqual(['2026-10-12', '2026-10-26'])
    expect([...initial]).toEqual(['2026-10-12'])
    expect([...toggleWeek(added, '2026-10-12')]).toEqual(['2026-10-26'])
  })
  it('contiguousRuns raggruppa in corse ordinate con buchi e cambio anno', () => {
    expect(contiguousRuns([])).toEqual([])
    expect(contiguousRuns(['2027-01-04', '2026-10-19', '2026-12-28', '2026-10-12', '2026-10-19'])).toEqual([
      { from: '2026-10-12', to: '2026-10-26' },
      { from: '2026-12-28', to: '2027-01-11' },
    ])
    expect(weekRangesLabel([
      { from: '2026-10-12', to: '2026-10-26' },
      { from: '2026-11-02', to: '2026-11-09' },
    ])).toBe('Settimane 42–43, Settimane 45–45')
  })
  it('expandWeekRanges accetta un singolo WeekRange o una lista', () => {
    expect(expandWeekRanges(null)).toEqual([])
    expect(expandWeekRanges({ from: '2026-10-12', to: '2026-10-26' })).toEqual(['2026-10-12', '2026-10-19'])
    expect(expandWeekRanges([{ from: '2026-10-12', to: '2026-10-19' }, { from: '2026-11-02', to: '2026-11-16' }])).toEqual([
      '2026-10-12',
      '2026-11-02',
      '2026-11-09',
    ])
  })
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
