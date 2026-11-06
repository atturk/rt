import { describe, expect, it } from 'vitest'
import type { Lesson } from './format'
import { lessonNeighbors } from './lessonNeighbors'

const lesson = (id: number, data: string, ora: string, materia: string, titolo = String(id), ready = true, docente = '') => ({
  id,
  data,
  ora,
  materia,
  titolo,
  docente,
  phases: { rewrite: ready ? 'VALID' : 'MISSING' },
} as unknown as Lesson)

const lessons = [
  lesson(5, '2026-10-07', '09:00', 'A'),
  lesson(3, '2026-10-06', '11:00', 'A'),
  lesson(1, '2026-10-05', '09:00', 'A'),
  lesson(4, '2026-10-06', '14:30', 'B'),
  lesson(2, '2026-10-06', '09:00', 'A', '2', false),
  lesson(6, '', '', 'A'),
]

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
    expect(lessonNeighbors(lessons, 99, { readyOnly: false })).toEqual({
      sameDay: { prev: null, next: null },
      sameSubject: { prev: null, next: null },
      sameTeacher: { prev: null, next: null, disabledReason: 'nessun docente per questa lezione' },
    })
  })

  it('a parità di data e ora usa il titolo', () => {
    const result = lessonNeighbors([lesson(1, '2026-10-06', '09:00', 'A', 'Zeta'), lesson(2, '2026-10-06', '09:00', 'A', 'Alfa')], 1, { readyOnly: false })
    expect(result.sameDay.prev?.id).toBe(2)
  })

  describe('sameTeacher (4.3.8b4 voce 9)', () => {
    it('lezione senza docente ha sameTeacher disattivato con motivo', () => {
      const list = [lesson(1, '2026-10-01', '09:00', 'Fisiologia', '1', true, '')]
      const res = lessonNeighbors(list, 1, { readyOnly: false })
      expect(res.sameTeacher).toEqual({
        prev: null,
        next: null,
        disabledReason: 'nessun docente per questa lezione',
      })
    })

    it('ordine cronologico delle lezioni dello stesso docente', () => {
      const list = [
        lesson(3, '2026-10-03', '10:00', 'Fisiologia', 'L3', true, 'Rossi'),
        lesson(1, '2026-10-01', '09:00', 'Fisiologia', 'L1', true, 'Rossi'),
        lesson(2, '2026-10-02', '09:00', 'Fisiologia', 'L2', true, 'Rossi'),
      ]
      const res = lessonNeighbors(list, 2, { readyOnly: false })
      expect(res.sameTeacher.prev?.id).toBe(1)
      expect(res.sameTeacher.next?.id).toBe(3)
    })

    it('confronto docente e materia insensibile a maiuscole e spazi', () => {
      const list = [
        lesson(1, '2026-10-01', '09:00', '  FISIOLOGIA  ', 'L1', true, ' Mario Rossi '),
        lesson(2, '2026-10-02', '09:00', 'fisiologia', 'L2', true, 'mario rossi'),
        lesson(3, '2026-10-03', '09:00', 'Fisiologia', 'L3', true, 'MARIO ROSSI'),
      ]
      const res = lessonNeighbors(list, 2, { readyOnly: false })
      expect(res.sameTeacher.prev?.id).toBe(1)
      expect(res.sameTeacher.next?.id).toBe(3)
    })

    it('due Rossi in materie diverse con lezioni alternate non si mescolano mai', () => {
      const list = [
        lesson(1, '2026-10-01', '09:00', 'Fisiologia', 'F1', true, 'Rossi'),
        lesson(2, '2026-10-02', '09:00', 'Anatomia', 'A1', true, 'Rossi'),
        lesson(3, '2026-10-03', '09:00', 'Fisiologia', 'F2', true, 'Rossi'),
        lesson(4, '2026-10-04', '09:00', 'Anatomia', 'A2', true, 'Rossi'),
        lesson(5, '2026-10-05', '09:00', 'Fisiologia', 'F3', true, 'Rossi'),
      ]
      // Da Fisiologia F2 (id: 3): prev deve essere F1 (id: 1), next deve essere F3 (id: 5), mai le lezioni di Anatomia
      const resF = lessonNeighbors(list, 3, { readyOnly: false })
      expect(resF.sameTeacher.prev?.id).toBe(1)
      expect(resF.sameTeacher.next?.id).toBe(5)

      // Da Anatomia A1 (id: 2): prev è null, next deve essere A2 (id: 4)
      const resA = lessonNeighbors(list, 2, { readyOnly: false })
      expect(resA.sameTeacher.prev).toBeNull()
      expect(resA.sameTeacher.next?.id).toBe(4)
    })
  })
})
