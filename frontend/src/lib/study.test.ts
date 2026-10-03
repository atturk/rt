import type { Lesson } from './format'
import { groupStudyPath, studyLessons } from './study'

const lesson = (id: number, extra: Partial<Lesson>) =>
  ({ id, materia: 'FISIOLOGIA', data: '2026-10-02', titolo: `Lezione ${id}`, folder_name: `f${id}`, docente: 'Rossi', phases: { rewrite: 'VALID' }, ...extra }) as Lesson

describe('Studio di un gruppo', () => {
  const lessons = [
    lesson(1, { data: '2026-10-02' }),
    lesson(2, { data: '2026-09-28' }),
    lesson(3, { data: '2026-10-02', phases: { rewrite: 'MISSING' } }),
    lesson(4, { data: '2026-10-02', materia: 'ANATOMIA', docente: ' Neri ' }),
  ]
  it('le lezioni pronte del gruppo, dalla più vecchia', () => {
    expect(studyLessons(lessons, { kind: 'materia', value: 'FISIOLOGIA' }).map((l) => l.id)).toEqual([2, 1])
    expect(studyLessons(lessons, { kind: 'giorno', value: '2026-10-02' }).map((l) => l.id)).toEqual([1, 4])
    expect(studyLessons(lessons, { kind: 'docente', value: 'Neri' }).map((l) => l.id)).toEqual([4])
  })
  it('indirizzi dai gruppi di Lezioni', () => {
    expect(groupStudyPath({ key: '2026-10-02' }, 'data')).toBe('/studio/giorno/2026-10-02')
    expect(groupStudyPath({ key: 'FISIOLOGIA' }, 'materia')).toBe('/studio/materia/FISIOLOGIA')
    expect(groupStudyPath({ key: 'Maria Rossi' }, 'docente')).toBe('/studio/docente/Maria%20Rossi')
    expect(groupStudyPath({ key: '' }, 'data')).toBeNull()
  })
})
