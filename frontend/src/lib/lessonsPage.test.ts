import type { Lesson } from './format'
import {
  formatDuration, groupLabel, markdownExportNote, lessonInfo, lessonStatus, lessonSubtitle, lessonsGroups, parseLessonsPrefs, selectionDetails, shortDate, sortSelection, subjectName,
} from './lessonsPage'

const lesson = (id: number, extra: Partial<Lesson> = {}) =>
  ({
    id, materia: 'FISIOLOGIA', data: '2026-10-02', titolo: `Lezione ${id}`, folder_name: `f${id}`, argomenti: '', docente: 'Rossi',
    phases: { build: 'VALID' }, pending_issues: 0, cost_usd: 0.42, unit_count: 9, duration_seconds: 3120, recall_questions: 38,
    recall_pending: 14, path: '', state: 'completato', ...extra,
  }) as Lesson

const NOW = new Date(2026, 9, 2, 10)

describe('dettagli della selezione', () => {
  const rows = [
    lesson(1, { duration_seconds: 3600, unit_count: 10, study_learned: 5, study_learning: 2, cost_usd: 2,
      recall_questions: 30, recall_pending: 10, study_last_at: '2026-10-01T10:00:00Z', data: '2026-09-28' }),
    lesson(2, { duration_seconds: 7200, unit_count: 20, study_learned: 7, study_learning: 3, cost_usd: 1,
      recall_questions: 20, recall_pending: 5, study_last_at: '2026-10-02T11:00:00Z', pending_issues: 3 }),
    lesson(3, { duration_seconds: null, unit_count: null, study_learned: 0, study_learning: 0, cost_usd: null,
      recall_questions: 0, recall_pending: 0, materia: 'PATOLOGIA', docente: '', error: 'Errore' }),
  ]
  it('somma i valori noti, sceglie l’ultimo studio e distingue pronta, da verificare ed errore', () => {
    const result = selectionDetails(rows)
    expect(result).toMatchObject({ count: 3, duration: 10800, firstDate: '2026-09-28', lastDate: '2026-10-02', units: 30,
      learned: 12, learning: 5, questions: 50, pending: 15, cost: 3, costPerHour: 1, ready: 1, toVerify: 1, errors: 1,
      lastStudy: { at: '2026-10-02T11:00:00Z', lesson: 'Lezione 2' },
      subjects: [{ name: 'Fisiologia', count: 2 }, { name: 'Patologia', count: 1 }],
      teachers: [{ name: 'Rossi', count: 2 }, { name: 'Senza docente', count: 1 }],
    })
    expect(result.percentages.learned).toBe(40)
    expect(result.percentages.learning).toBeCloseTo(100 / 6)
    expect(result.percentages.toLearn).toBeCloseTo(100 - 40 - 100 / 6)
  })
  it('distingue dati mancanti da zero, senza divisioni per zero', () => {
    const missing = selectionDetails([lesson(1, { duration_seconds: null, unit_count: null, cost_usd: null, data: '', study_last_at: 'non valida' })])
    expect(missing).toMatchObject({ duration: null, units: null, cost: null, costPerHour: null, lastStudy: null, firstDate: null })
    expect(selectionDetails([lesson(1, { duration_seconds: 0, cost_usd: 0, unit_count: 0 })])).toMatchObject({
      duration: 0, cost: 0, units: 0, costPerHour: null, percentages: { learned: 0, learning: 0, toLearn: 0 },
    })
    expect(selectionDetails([])).toMatchObject({ count: 0, duration: null, units: null, questions: null, subjects: [], teachers: [] })
  })
  it('ordina tutte le colonne e lascia i dati mancanti in fondo, senza mutare l’elenco', () => {
    const sorted = (key: Parameters<typeof sortSelection>[1], direction: 'asc' | 'desc' = 'desc') => sortSelection(rows, key, direction).map(l => l.id)
    expect(sorted('costo')).toEqual([1, 2, 3])
    expect(sorted('costo', 'asc')).toEqual([2, 1, 3])
    expect(sorted('audio')).toEqual([2, 1, 3])
    expect(sorted('studio')).toEqual([1, 2, 3])
    expect(sorted('domande')).toEqual([1, 2, 3])
    expect(sorted('lezione', 'asc')).toEqual([1, 2, 3])
    expect(rows.map(l => l.id)).toEqual([1, 2, 3])
  })
})

describe('lessonSubtitle', () => {
  const l = lesson(1)
  it('per data: materia, docente e unità (la data la dice il gruppo)', () => {
    expect(lessonSubtitle(l, 'data', NOW)).toBe('Fisiologia · Rossi · 9 unità · 38 domande')
  })
  it('per mese: data, materia, docente e unità', () => {
    expect(lessonSubtitle(l, 'mese', NOW)).toBe('2 ott · Fisiologia · Rossi · 9 unità · 38 domande')
  })
  it('per materia: data, docente e unità', () => {
    expect(lessonSubtitle(l, 'materia', NOW)).toBe('2 ott · Rossi · 9 unità · 38 domande')
  })
  it('per docente: data, materia e unità', () => {
    expect(lessonSubtitle(l, 'docente', NOW)).toBe('2 ott · Fisiologia · 9 unità · 38 domande')
  })
  it('i campi mancanti si saltano, senza separatori doppi', () => {
    expect(lessonSubtitle(lesson(2, { docente: '', unit_count: null }), 'data', NOW)).toBe('Fisiologia · 38 domande')
    expect(lessonSubtitle(lesson(3, { data: '', materia: '' }), 'docente', NOW)).toBe('9 unità · 38 domande')
  })
  it('aggiunge le domande e non le unità apprese', () => {
    expect(lessonSubtitle(lesson(1, { study_learned: 7, recall_questions: 4 }), 'data', NOW)).toBe('Fisiologia · Rossi · 9 unità · 4 domande')
  })
})

it('senza domande non aggiunge il conteggio', () => { expect(lessonSubtitle(lesson(1, { recall_questions: 0, study_learned: 7 }), 'data', NOW)).toBe('Fisiologia · Rossi · 9 unità') })

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
  it('per mese: gruppi per mese con etichetta monthLabel', () => {
    const groups = lessonsGroups(lessons, { group: 'mese', sort: 'recenti' }, NOW)
    expect(groups.map((g) => g.label)).toEqual(['Ottobre 2026'])
    expect(groups[0].lessons).toHaveLength(3)
  })
  it('studio recente: mai studiate in fondo per data, senza cambiare i gruppi', () => {
    const rows = [lesson(1, { study_last_at: '2026-10-01T20:00:00Z' }), lesson(2, { study_last_at: '2026-10-02T12:00:00Z' }),
      lesson(3, { data: '2026-10-01' }), lesson(4, { data: '2026-10-02' })]
    expect(lessonsGroups(rows, { group: 'materia', sort: 'studio-recente' }, NOW)[0].lessons.map(l => l.id)).toEqual([2, 1, 4, 3])
  })
  it('percentuali e spareggio per le unità in apprendimento, con unità mancanti o zero', () => {
    const rows = [lesson(1, { unit_count: 10, study_learned: 5, study_learning: 1 }),
      lesson(2, { unit_count: 20, study_learned: 10, study_learning: 3 }),
      lesson(3, { unit_count: 3, study_learned: 3 }), lesson(4, { unit_count: 0 }), lesson(5, { unit_count: null })]
    expect(lessonsGroups(rows, { group: 'materia', sort: 'piu-avanti' }, NOW)[0].lessons.map(l => l.id)).toEqual([3, 2, 1, 5, 4])
    expect(lessonsGroups(rows, { group: 'materia', sort: 'piu-indietro' }, NOW)[0].lessons.map(l => l.id)).toEqual([5, 4, 1, 2, 3])
    expect(rows.map(l => l.id)).toEqual([1, 2, 3, 4, 5])
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

it('preferenze salvate e preferenze illeggibili', () => {
  expect(parseLessonsPrefs('{"group":"docente","sort":"titolo"}')).toEqual({ group: 'docente', sort: 'titolo' })
  expect(parseLessonsPrefs('{"group":"mese"}')).toEqual({ group: 'mese', sort: 'recenti' })
  expect(parseLessonsPrefs('{"group":"data"}')).toEqual({ group: 'data', sort: 'recenti' })
  expect(parseLessonsPrefs('{"group":"sconosciuto"}')).toEqual({ group: 'data', sort: 'recenti' })
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

it('esclude le ignorate dal denominatore, le mostra nella barra e non nel sottotitolo', () => {
  const rows = [lesson(1, { unit_count: 10, study_learned: 4, study_ignored: 5 }), lesson(2, { unit_count: 10, study_learned: 5 })]
  expect(lessonsGroups(rows, { group: 'materia', sort: 'piu-avanti' }, NOW)[0].lessons.map(l => l.id)).toEqual([1, 2])
  expect(lessonsGroups(rows, { group: 'materia', sort: 'piu-indietro' }, NOW)[0].lessons.map(l => l.id)).toEqual([2, 1])
  expect(sortSelection(rows, 'studio', 'desc').map(l => l.id)).toEqual([1, 2])
  expect(selectionDetails(rows)).toMatchObject({ units: 20, studyUnits: 15, ignored: 5, percentages: { learned: 45, ignored: 25, toLearn: 30 } })
  expect(lessonSubtitle(rows[0], 'data', NOW)).not.toContain('ignorate')
  expect(selectionDetails([lesson(1, { unit_count: 2, study_ignored: 2 })]).studyUnits).toBe(0)
})
