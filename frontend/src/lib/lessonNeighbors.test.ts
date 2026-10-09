import { describe, expect, it } from 'vitest'
import type { Lesson } from './format'
import { lessonNeighbors } from './lessonNeighbors'
const lesson = (id: number, data: string, ora: string, materia: string, titolo = String(id), ready = true) => ({ id, data, ora, materia, titolo, phases: { rewrite: ready ? 'VALID' : 'MISSING' } } as unknown as Lesson)
const lessons = [lesson(5, '2026-10-07', '09:00', 'A'), lesson(3, '2026-10-06', '11:00', 'A'), lesson(1, '2026-10-05', '09:00', 'A'), lesson(4, '2026-10-06', '14:30', 'B'), lesson(2, '2026-10-06', '09:00', 'A', '2', false), lesson(6, '', '', 'A')]
describe('vicini di una lezione', () => {
  it('ordina giorno e ora, filtra le pronte senza cambiare l’elenco', () => {
    const result = lessonNeighbors(lessons, 3, { readyOnly: true })
    expect(result.sameDay.prev).toBeNull()
    expect(result.sameDay.next?.id).toBe(4)
    expect(result.sameSubject.prev?.id).toBe(1)
    expect(result.sameSubject.next?.id).toBe(5)
    expect(lessons[0].id).toBe(5)
    expect(lessonNeighbors(lessons, 3, { readyOnly: false }).sameDay.prev?.id).toBe(2)
  })
  it('senza data in fondo; non inventa un giorno né un vicino', () => {
    const result = lessonNeighbors(lessons, 6, { readyOnly: true })
    expect(result.sameSubject.prev?.id).toBe(5)
    expect(result.sameSubject.next).toBeNull()
    expect(result.sameDay).toEqual({ prev: null, next: null })
    expect(lessonNeighbors(lessons, 99, { readyOnly: false })).toEqual({ sameDay: { prev: null, next: null }, sameSubject: { prev: null, next: null } })
  })
  it('a parità di data e ora usa il titolo', () => {
    const result = lessonNeighbors([lesson(1, '2026-10-06', '09:00', 'A', 'Zeta'), lesson(2, '2026-10-06', '09:00', 'A', 'Alfa')], 1, { readyOnly: false })
    expect(result.sameDay.prev?.id).toBe(2)
  })
})
