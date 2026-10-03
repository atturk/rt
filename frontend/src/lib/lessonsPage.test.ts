import type { Lesson } from './format'
import {
  formatDuration, groupLabel, markdownExportNote, groupRecallPath, lessonInfo, lessonStatus, lessonSubtitle, lessonsGroups, parseLessonsPrefs, shortDate, subjectName,
} from './lessonsPage'

const lesson = (id: number, extra: Partial<Lesson> = {}) =>
  ({
    id, materia: 'FISIOLOGIA', data: '2026-10-02', titolo: `Lezione ${id}`, folder_name: `f${id}`, argomenti: '', docente: 'Rossi',
    phases: { build: 'VALID' }, pending_issues: 0, cost_usd: 0.42, unit_count: 9, duration_seconds: 3120, recall_questions: 38,
    recall_pending: 14, path: '', state: 'completato', ...extra,
  }) as Lesson

const NOW = new Date(2026, 9, 2, 10)

describe('lessonSubtitle', () => {
  const l = lesson(1)
  it('per data: materia, docente e unità (la data la dice il gruppo)', () => {
    expect(lessonSubtitle(l, 'data', NOW)).toBe('Fisiologia · Rossi · 9 unità')
  })
  it('per materia: data, docente e unità', () => {
    expect(lessonSubtitle(l, 'materia', NOW)).toBe('2 ott · Rossi · 9 unità')
  })
  it('per docente: data, materia e unità', () => {
    expect(lessonSubtitle(l, 'docente', NOW)).toBe('2 ott · Fisiologia · 9 unità')
  })
  it('i campi mancanti si saltano, senza separatori doppi', () => {
    expect(lessonSubtitle(lesson(2, { docente: '', unit_count: null }), 'data', NOW)).toBe('Fisiologia')
    expect(lessonSubtitle(lesson(3, { data: '', materia: '' }), 'docente', NOW)).toBe('9 unità')
  })
})

describe('formati', () => {
  it('data breve con l’anno solo se diverso', () => {
    expect(shortDate('2026-09-30', NOW)).toBe('30 set')
    expect(shortDate('2025-09-30', NOW)).toBe('30 set 2025')
  })
  it('materia leggibile, durata in minuti', () => {
    expect(subjectName('FISIOLOGIA')).toBe('Fisiologia')
    expect(subjectName('Fisiologia generale')).toBe('Fisiologia generale')
    expect(formatDuration(3120)).toBe('52 min')
    expect(formatDuration(3900)).toBe('1 h 05 min')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('lessonsGroups', () => {
  const lessons = [
    lesson(1, { data: '2026-10-02', materia: 'FISIOLOGIA', docente: 'Rossi', titolo: 'Zeta' }),
    lesson(2, { data: '2026-10-01', materia: 'FARMACOLOGIA', docente: 'Bianchi', titolo: 'Alfa' }),
    lesson(3, { data: '2026-10-02', materia: 'FARMACOLOGIA', docente: '', titolo: 'Beta' }),
  ]
  it('per data: Oggi in cima, ordine scelto dentro i gruppi', () => {
    const groups = lessonsGroups(lessons, { group: 'data', sort: 'titolo' }, NOW)
    expect(groups.map((g) => g.label)).toEqual(['Oggi · venerdì 2 ottobre', 'Ieri · giovedì 1 ottobre'])
    expect(groups[0].lessons.map((l) => l.id)).toEqual([3, 1])
    expect(lessonsGroups(lessons, { group: 'data', sort: 'meno-recenti' }, NOW)[0].key).toBe('2026-10-01')
  })
  it('per materia e per docente, "Senza docente" in fondo', () => {
    const bySubject = lessonsGroups(lessons, { group: 'materia', sort: 'recenti' }, NOW)
    expect(bySubject.map((g) => groupLabel(g, 'materia'))).toEqual(['Farmacologia', 'Fisiologia'])
    expect(lessonsGroups(lessons, { group: 'docente', sort: 'recenti' }, NOW).map((g) => g.label)).toEqual(['Bianchi', 'Rossi', 'Senza docente'])
  })
  it('recall del gruppo: giorno o materia; per docente non c’è', () => {
    const [day] = lessonsGroups(lessons, { group: 'data', sort: 'recenti' }, NOW)
    expect(groupRecallPath(day, 'data')).toBe('/recall/giorno/2026-10-02')
    const [subject] = lessonsGroups(lessons, { group: 'materia', sort: 'recenti' }, NOW)
    expect(groupRecallPath(subject, 'materia')).toBe('/recall/materie/FARMACOLOGIA')
    const [teacher] = lessonsGroups(lessons, { group: 'docente', sort: 'recenti' }, NOW)
    expect(groupRecallPath(teacher, 'docente')).toBeNull()
  })
})

describe('stato e Info', () => {
  it('il pallino: in corso prima di tutto, poi errore, da verificare, pronta', () => {
    expect(lessonStatus(lesson(1, { pending_issues: 2 }), true)).toBe('in-corso')
    expect(lessonStatus(lesson(1, { error: 'illeggibile' }), false)).toBe('errore')
    expect(lessonStatus(lesson(1, { pending_issues: 2 }), false)).toBe('da-verificare')
    expect(lessonStatus(lesson(1), false)).toBe('pronta')
    expect(lessonStatus(lesson(1, { phases: { build: 'MISSING' } }), false)).toBe('da-completare')
  })
  it('Info: tutti i campi elisi dalla riga', () => {
    expect(Object.fromEntries(lessonInfo(lesson(1, { pending_issues: 2 }), false, NOW))).toEqual({
      Materia: 'Fisiologia',
      Docente: 'Rossi',
      Data: 'venerdì 2 ottobre',
      Durata: '52 min',
      Unità: '9',
      Domande: '38 nel pool · 14 da fare',
      Costo: '$0.42',
      Stato: 'completata · 2 da verificare',
    })
  })
})

it('preferenze illeggibili tornano a quelle predefinite', () => {
  expect(parseLessonsPrefs('{"group":"docente","sort":"titolo"}')).toEqual({ group: 'docente', sort: 'titolo' })
  expect(parseLessonsPrefs('{"group":"mese"}')).toEqual({ group: 'data', sort: 'recenti' })
  expect(parseLessonsPrefs('non json')).toEqual({ group: 'data', sort: 'recenti' })
})

describe('markdownExportNote', () => {
  it('nessuna selezione o nessun documento finale: non disponibile, con il motivo', () => {
    expect(markdownExportNote([]).unavailable).toBe('nessuna lezione selezionata')
    expect(markdownExportNote([lesson(1, { phases: { build: 'MISSING' } })]).unavailable).toMatch(/documento finale.*anteprima/)
    expect(markdownExportNote([lesson(1, { phases: {} }), lesson(2, { phases: {} })]).unavailable).toMatch(/^nessuna lezione selezionata ha il documento finale/)
  })
  it('in parte: disponibile, il suggerimento dice quali restano fuori', () => {
    const note = markdownExportNote([lesson(1), lesson(2, { phases: { build: 'STALE' } })])
    expect(note.unavailable).toBeNull()
    expect(note.hint).toBe('1 di 2: Lezione 2 senza documento finale')
  })
  it('tutte con il documento finale: nessuna nota', () => {
    expect(markdownExportNote([lesson(1)])).toEqual({ unavailable: null, hint: null })
  })
})
