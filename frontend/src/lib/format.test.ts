import { groupBySubject, lessonTitle, phaseTone, type Lesson } from './format'

const lesson = (over: Partial<Lesson>): Lesson =>
  ({ id: 1, folder_name: 'x', path: '/x', data: '', materia: '', titolo: '', argomenti: '', phases: {}, pending_issues: 0, ...over }) as Lesson

describe('lessonTitle', () => {
  it('toglie data e materia dal nome come la web Gradio', () => {
    expect(lessonTitle(lesson({ titolo: '[2026-03-02] FISIOLOGIA - Il rene', materia: 'FISIOLOGIA' }))).toBe('Il rene')
  })
  it('usa la cartella se manca il titolo', () => {
    expect(lessonTitle(lesson({ folder_name: 'Lezione 3' }))).toBe('Lezione 3')
  })
})

describe('groupBySubject', () => {
  it('raggruppa per materia in ordine alfabetico, lezioni dalla più recente', () => {
    const groups = groupBySubject([
      lesson({ id: 1, materia: 'FISIOLOGIA', data: '2026-01-01', titolo: 'a' }),
      lesson({ id: 2, materia: 'ANATOMIA', data: '2026-01-01', titolo: 'b' }),
      lesson({ id: 3, materia: 'FISIOLOGIA', data: '2026-02-01', titolo: 'c' }),
      lesson({ id: 4, titolo: 'd' }),
    ])
    expect(groups.map(([s]) => s)).toEqual(['Altre lezioni', 'ANATOMIA', 'FISIOLOGIA'])
    expect(groups[2][1].map((l) => l.id)).toEqual([3, 1])
  })
})

it('phaseTone', () => {
  expect(phaseTone('VALID')).toBe('success')
  expect(phaseTone('STALE')).toBe('warning')
  expect(phaseTone('INVALID')).toBe('danger')
  expect(phaseTone('MISSING')).toBe('neutral')
})
