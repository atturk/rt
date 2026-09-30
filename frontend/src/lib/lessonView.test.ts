import type { Lesson } from './format'
import { dayLabel, groupLessons, monthLabel, parseViewPrefs, sortLessons } from './lessonView'

const lesson = (id: number, materia: string, data: string, extra: Partial<Lesson> = {}) =>
  ({ id, materia, data, titolo: `Lezione ${id}`, folder_name: `f${id}`, argomenti: '', phases: {}, pending_issues: 0, cost_usd: 0, ...extra }) as unknown as Lesson

const LESSONS = [
  lesson(1, 'ANATOMIA', '2026-09-12', { pending_issues: 3, cost_usd: 0.5, titolo: 'Zeta' }),
  lesson(2, 'FISIOLOGIA', '2026-09-29', { cost_usd: 0.1, titolo: 'alfa', state: 'completato' }),
  lesson(3, '', '', { titolo: 'Beta', state: 'fallito' }),
  lesson(4, 'ANATOMIA', '2026-08-30', { pending_issues: 1, titolo: 'Gamma' }),
  lesson(5, 'FISIOLOGIA', '2026-09-29', { titolo: 'Delta' }),
]
const ids = (lessons: Lesson[]) => lessons.map((l) => l.id)
const NOW = new Date(2026, 8, 29, 10)

describe('sortLessons', () => {
  it('per data: più recenti prima, senza data in fondo in entrambe le direzioni', () => {
    expect(ids(sortLessons(LESSONS, 'data', 'desc'))).toEqual([5, 2, 1, 4, 3])
    expect(ids(sortLessons(LESSONS, 'data', 'asc'))).toEqual([4, 1, 5, 2, 3])
  })
  it('per titolo senza distinguere maiuscole, per issue, costo e stato', () => {
    expect(ids(sortLessons(LESSONS, 'titolo', 'asc'))).toEqual([2, 3, 5, 4, 1])
    expect(ids(sortLessons(LESSONS, 'issue', 'desc')).slice(0, 2)).toEqual([1, 4])
    expect(ids(sortLessons(LESSONS, 'costo', 'desc')).slice(0, 2)).toEqual([1, 2])
    expect(ids(sortLessons(LESSONS, 'stato', 'asc'))[0]).toBe(3)
  })
  it('non modifica l’elenco originale', () => {
    const copy = [...LESSONS]
    sortLessons(LESSONS, 'titolo', 'asc')
    expect(LESSONS).toEqual(copy)
  })
})

describe('groupLessons', () => {
  it('per giorno, con Oggi e i giorni senza data in fondo', () => {
    const groups = groupLessons(sortLessons(LESSONS, 'data', 'desc'), 'giorno', 'desc', NOW)
    expect(groups.map((g) => g.key)).toEqual(['2026-09-29', '2026-09-12', '2026-08-30', ''])
    expect(groups[0].label).toBe('Oggi · martedì 29 settembre')
    expect(ids(groups[0].lessons)).toEqual([5, 2])
    expect(groups.at(-1)!.label).toBe('Senza data')
  })
  it('per mese segue la direzione della data', () => {
    const groups = groupLessons(sortLessons(LESSONS, 'data', 'asc'), 'mese', 'asc', NOW)
    expect(groups.map((g) => g.label)).toEqual(['Agosto 2026', 'Settembre 2026', 'Senza data'])
  })
  it('per materia in ordine alfabetico, mantenendo l’ordine dentro il gruppo', () => {
    const groups = groupLessons(sortLessons(LESSONS, 'titolo', 'asc'), 'materia')
    expect(groups.map((g) => g.label)).toEqual(['ANATOMIA', 'FISIOLOGIA', 'Senza materia'])
    expect(ids(groups[0].lessons)).toEqual([4, 1])
  })
  it('nessun raggruppamento: un solo gruppo', () => {
    expect(groupLessons(LESSONS, 'nessuno')).toHaveLength(1)
  })
})

describe('etichette delle date', () => {
  it('ieri, giorni di altri anni e mesi', () => {
    expect(dayLabel('2026-09-28', NOW)).toBe('Ieri · lunedì 28 settembre')
    expect(dayLabel('2025-09-03', NOW)).toBe('Mercoledì 3 settembre 2025')
    expect(monthLabel('2026-01-15')).toBe('Gennaio 2026')
    expect(dayLabel('boh', NOW)).toBe('boh')
  })
})

describe('parseViewPrefs', () => {
  it('scarta valori sconosciuti e JSON non valido', () => {
    expect(parseViewPrefs('{"view":"tabella","sort":"x","group":"materia","collapsed":["materia:A",3]}')).toEqual({
      view: 'tabella', sort: 'data', dir: 'desc', group: 'materia', collapsed: ['materia:A'],
    })
    expect(parseViewPrefs('{rotto').view).toBe('schede')
    expect(parseViewPrefs(null).group).toBe('nessuno')
  })
})
