import type { LessonRecallStats } from '@/api/recall'
import type { Lesson } from './format'
import { groupForRecall, parseRecallPrefs, subjectPath, subjectTotals } from './recallView'

const lesson = (id: number, materia: string, data: string, titolo = `L${id}`) =>
  ({ id, materia, data, titolo, folder_name: `f${id}`, argomenti: '', path: '', phases: {}, pending_issues: 0 }) as unknown as Lesson

const stat = (id: number, pending: number, answers = 0, ready = true): LessonRecallStats =>
  ({ lesson_id: id, ready, questions: pending ? { quiz: { pending, answered: answers } } : {}, answers, telegram: false })

const LESSONS = [lesson(1, 'FISIOLOGIA', '2026-09-01'), lesson(2, 'BIOCHIMICA', '2026-09-03'), lesson(3, 'BIOCHIMICA', '2026-09-02'), lesson(4, '', '2026-09-04')]
const STATS = new Map([stat(1, 3), stat(2, 1, 2), stat(3, 5), stat(4, 0, 0, false)].map((s) => [s.lesson_id, s]))

describe('pagina del recall per materia', () => {
  it('raggruppa per materia in ordine alfabetico, senza materia in fondo', () => {
    const groups = groupForRecall(LESSONS, STATS, { sort: 'data', dir: 'desc' })
    expect(groups.map((g) => g.label)).toEqual(['BIOCHIMICA', 'FISIOLOGIA', 'Senza materia'])
    expect(groups[0].lessons.map((l) => l.id)).toEqual([2, 3])
  })

  it('ordina dentro la materia per domande da porre', () => {
    const groups = groupForRecall(LESSONS, STATS, { sort: 'domande', dir: 'desc' })
    expect(groups[0].lessons.map((l) => l.id)).toEqual([3, 2])
    expect(groupForRecall(LESSONS, STATS, { sort: 'domande', dir: 'asc' })[0].lessons.map((l) => l.id)).toEqual([2, 3])
  })

  it('somma le domande da porre e le risposte della materia', () => {
    expect(subjectTotals(LESSONS.slice(1, 3), STATS)).toEqual({ ready: 2, pending: 6, answers: 2 })
  })

  it('scarta preferenze sconosciute e codifica la materia nel link', () => {
    expect(parseRecallPrefs('{"view":"tabella","sort":"costo","collapsed":["materia:X",3]}')).toEqual({
      view: 'tabella', sort: 'data', dir: 'desc', collapsed: ['materia:X'],
    })
    expect(parseRecallPrefs('non json').view).toBe('schede')
    expect(subjectPath('PATOLOGIA GENERALE 2')).toBe('/recall/materie/PATOLOGIA%20GENERALE%202')
  })
})
