import { describe, expect, it } from 'vitest'

import type { Lesson } from './format'
import { dateForms, filterLessons, matchesQuery } from './lessonSearch'

function lesson(over: Partial<Lesson>): Lesson {
  return {
    id: 1,
    folder_name: '[2026-09-26] ANATOMIA - Arti superiori',
    path: '/x',
    data: '2026-09-26',
    materia: 'ANATOMIA',
    titolo: '',
    argomenti: 'Arti superiori, plesso brachiale',
    state: 'completato',
    phases: {},
    pending_issues: 0,
    cost_usd: null,
    error: null,
    ...over,
  } as Lesson
}

describe('ricerca delle lezioni', () => {
  const l = lesson({})

  it('cerca in titolo, argomenti e materia senza maiuscole e accenti', () => {
    expect(matchesQuery(l, 'anatomia')).toBe(true)
    expect(matchesQuery(l, 'PLESSO')).toBe(true)
    expect(matchesQuery(lesson({ argomenti: 'Perché il cuore batte' }), 'perche')).toBe(true)
    expect(matchesQuery(l, 'fisiologia')).toBe(false)
  })

  it('cerca la data in più formati', () => {
    for (const q of ['2026-09-26', '26/09/2026', '26/9/2026', '26-09-2026', '26.09.2026', '26/09', '26 settembre 2026', 'settembre'])
      expect(matchesQuery(l, q), q).toBe(true)
    expect(matchesQuery(l, '27/09/2026')).toBe(false)
    expect(dateForms('')).toEqual([])
    expect(dateForms('26 sett')).toEqual(['26 sett'])
  })

  it('con più parole vuole tutte le parole', () => {
    expect(matchesQuery(l, 'anatomia 26/09/2026')).toBe(true)
    expect(matchesQuery(l, 'anatomia rene')).toBe(false)
    expect(matchesQuery(l, '   ')).toBe(true)
  })

  it('filtra per testo, materia e stato', () => {
    const lessons = [l, lesson({ id: 2, materia: 'FISIOLOGIA', argomenti: 'Il rene', state: 'preparato' })]
    expect(filterLessons(lessons, { materia: 'FISIOLOGIA' }).map((x) => x.id)).toEqual([2])
    expect(filterLessons(lessons, { state: 'completato' }).map((x) => x.id)).toEqual([1])
    expect(filterLessons(lessons, { q: 'rene' }).map((x) => x.id)).toEqual([2])
    expect(filterLessons(lessons, {}).length).toBe(2)
  })
})
