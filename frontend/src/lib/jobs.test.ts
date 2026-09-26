import { audioFileProblem, decisionLink, describeEvent, jobTypeLabel, mergeEvents, progressLabel, progressPercent, progressTitle, type JobEvent } from './jobs'

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

describe('avanzamento delle fasi a unità (RT4-FA1)', () => {
  it('mostra fase e unità sul totale dai dati strutturati', () => {
    const progress = { phase: 'review', current: 8, total: 31, message: 'testo libero ignorato', unit_id: '4.1', unit_title: 'Glicolisi', failed: 0 }
    expect(progressTitle(progress)).toBe('Revisione · 8/31')
    expect(progressLabel(progress)).toEqual({ phase: 'Revisione', count: '8/31', detail: '4.1 Glicolisi' })
  })
  it('segnala le unità non riuscite e ricade sul messaggio senza unità', () => {
    expect(progressLabel({ phase: 'rewrite', current: 3, total: 9, unit_id: '1.3', failed: 2 }).detail).toBe('1.3 · 2 unità non riuscite')
    expect(progressLabel({ phase: 'setup', message: 'Trascrizione' })).toEqual({ phase: 'Trascrizione e setup', count: null, detail: 'Trascrizione' })
    expect(progressTitle(null)).toBeNull()
  })
  it('una fase finita parziale è un avviso con le unità completate', () => {
    const e = event(9, 'phase_completed', { phase: 'review', partial: true, result: { completed_units: 30, expected_units: 31 } })
    expect(describeEvent(e)).toEqual({ text: 'Revisione: parziale (30/31 unità)', tone: 'warning' })
    expect(describeEvent(event(10, 'job_queued', { retry_of: 'abc' })).text).toBe('In coda (nuovo tentativo di un job fallito)')
  })
})
