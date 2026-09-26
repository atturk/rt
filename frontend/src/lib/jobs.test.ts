import { audioFileProblem, decisionLink, describeEvent, jobTypeLabel, mergeEvents, progressPercent, type JobEvent } from './jobs'

const event = (id: number, type = 'notice', payload: Record<string, unknown> = {}): JobEvent => ({ id, job_id: 'j', type, payload })

describe('describeEvent', () => {
  it('traduce gli eventi delle fasi in italiano', () => {
    expect(describeEvent(event(1, 'phase_started', { phase: 'outline', step: 3, total_steps: 6 }))).toEqual({
      text: 'Scaletta: avviata (3/6)',
      tone: 'neutral',
    })
    expect(describeEvent(event(2, 'phase_progress', { phase: 'rewrite', current: 2, total: 5, message: 'unità U2' })).text).toBe(
      'Rielaborazione: 2/5 unità U2',
    )
    expect(describeEvent(event(3, 'phase_failed', { phase: 'setup', message: 'ffmpeg mancante' }))).toEqual({
      text: 'Trascrizione e setup: errore. ffmpeg mancante',
      tone: 'danger',
    })
  })
  it('segnala decisioni e fine del job con il tono giusto', () => {
    expect(describeEvent(event(4, 'decision_required', { kind: 'outline_approval' }))).toEqual({
      text: 'Serve la tua decisione: approvare la scaletta',
      tone: 'warning',
    })
    expect(describeEvent(event(5, 'job_finished', { state: 'failed', error: 'boom' }))).toEqual({ text: 'Fallito: boom', tone: 'danger' })
    expect(describeEvent(event(6, 'job_finished', { state: 'succeeded' })).tone).toBe('success')
  })
})

describe('progressPercent', () => {
  it('usa current/total o i passi della pipeline', () => {
    expect(progressPercent({ current: 1, total: 4 })).toBe(25)
    expect(progressPercent({ phase: 'outline', step: 3, total_steps: 6 })).toBe(33)
    expect(progressPercent({ phase: 'outline', step: 3, total_steps: 6, completed: true })).toBe(50)
    expect(progressPercent(null)).toBeNull()
    expect(progressPercent({ phase: 'x' })).toBeNull()
  })
})

describe('audioFileProblem', () => {
  it('controlla formato e file vuoti prima dell\'upload', () => {
    expect(audioFileProblem([])).toMatch(/almeno un file/)
    expect(audioFileProblem([{ name: 'note.txt', size: 3 }])).toMatch(/Formato non supportato: note.txt/)
    expect(audioFileProblem([{ name: 'LEZIONE.M4A', size: 0 }])).toMatch(/vuoto/)
    expect(audioFileProblem([{ name: 'a.m4a', size: 10 }, { name: 'b.wav', size: 10 }])).toBeNull()
  })
})

describe('mergeEvents', () => {
  it('scarta i duplicati di una ripresa e ordina per id', () => {
    const merged = mergeEvents([event(1), event(2)], [event(2), event(4), event(3)])
    expect(merged.map((e) => e.id)).toEqual([1, 2, 3, 4])
    const same = [event(1)]
    expect(mergeEvents(same, [event(1)])).toBe(same)
  })
})

describe('etichette dei job', () => {
  it('nomina la fase dei job run_phase e porta alla decisione giusta', () => {
    expect(jobTypeLabel({ type: 'run_phase', payload: { phase: 'review' } })).toBe('Fase: Revisione')
    expect(jobTypeLabel({ type: 'run_pipeline', payload: {} })).toBe('Pipeline completa')
    expect(decisionLink({ lesson_id: 7, decision: { kind: 'outline_approval' } })).toBe('/lezioni/7/outline')
    expect(decisionLink({ lesson_id: 7, decision: { kind: 'science_issue' } })).toBe('/lezioni/7')
    expect(decisionLink({ lesson_id: null, decision: null })).toBeNull()
  })
})
