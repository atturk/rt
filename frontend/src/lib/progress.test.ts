import { describe, expect, it } from 'vitest'

import { jobPhases, phaseProgress, progressSummary } from './progress'

const pipeline = (progress: Record<string, unknown> | null, state = 'running', withReview = true) => ({
  type: 'run_pipeline',
  state,
  payload: { inputs: ['/tmp/upload/lezione.m4a'], options: { with_review: withReview } },
  progress,
})

describe('jobPhases', () => {
  it('pipeline dall’audio: trascrizione, poi le fasi; la revisione solo se richiesta', () => {
    expect(jobPhases(pipeline(null))).toEqual(['setup', 'prepare', 'outline', 'rewrite', 'review', 'build'])
    expect(jobPhases(pipeline(null, 'running', false))).toEqual(['setup', 'prepare', 'outline', 'rewrite', 'build'])
    expect(jobPhases({ type: 'run_pipeline', payload: { inputs: ['/lezioni/[2026-09-05] BIO'], options: {} } })).toEqual([
      'prepare', 'outline', 'rewrite', 'build',
    ])
  })

  it('fase singola e unità', () => {
    expect(jobPhases({ type: 'run_phase', payload: { phase: 'review' } })).toEqual(['review'])
    expect(jobPhases({ type: 'rewrite_unit', payload: {} })).toEqual(['rewrite'])
    expect(jobPhases({ type: 'recall_generate', payload: {} })).toEqual([])
  })
})

describe('phaseProgress', () => {
  it('totale = (fasi finite + avanzamento della fase) / numero di fasi', () => {
    // Rielaborazione, unità 10 di 12: fase 4 di 6, totale (3 + 10/12) / 6 = 64%
    const p = phaseProgress(pipeline({ phase: 'rewrite', current: 10, total: 12 }))
    expect(p).toMatchObject({ phase: 'Rielaborazione', detail: 'unità 10 di 12', step: 4, steps: 6 })
    expect(p.phaseFraction).toBeCloseTo(10 / 12)
    expect(p.overall).toBeCloseTo((3 + 10 / 12) / 6)
    expect(progressSummary(p)).toBe('fase 4 di 6 · 64%')
  })

  it('fase appena iniziata e fase completata', () => {
    expect(phaseProgress(pipeline({ phase: 'outline', step: null })).overall).toBeCloseTo(2 / 6)
    const completed = phaseProgress(pipeline({ phase: 'outline', completed: true }))
    expect(completed.phaseFraction).toBe(1)
    expect(completed.overall).toBeCloseTo(3 / 6)
    expect(completed.detail).toBeNull()
  })

  it('trascrizione: il dettaglio è il messaggio con la percentuale', () => {
    const p = phaseProgress(pipeline({ phase: 'setup', current: 42, total: 100, message: 'Trascrizione audio: 42%' }))
    expect(p).toMatchObject({ phase: 'Trascrizione', detail: 'Trascrizione audio: 42%', step: 1 })
    expect(p.overall).toBeCloseTo(0.42 / 6)
  })

  it('in coda è zero, finito è tutto', () => {
    expect(phaseProgress(pipeline(null, 'queued'))).toMatchObject({ phase: null, overall: 0, step: 1 })
    expect(phaseProgress(pipeline({ phase: 'build', current: 1, total: 3 }, 'succeeded')).overall).toBe(1)
  })

  it('job di un’altra fase (domande di recall): una fase sola, percentuale senza "fase N di M"', () => {
    const p = phaseProgress({ type: 'recall_generate', state: 'running', payload: {}, progress: { phase: 'recall', current: 1, total: 4 } })
    expect(p).toMatchObject({ phase: 'Domande di recall', detail: '1 di 4', step: 1, steps: 1, overall: 0.25 })
    expect(progressSummary(p)).toBe('25%')
  })

  it('una fase fuori dall’elenco previsto conta come fase unica', () => {
    const p = phaseProgress(pipeline({ phase: 'review', current: 1, total: 2 }, 'running', false))
    expect(p).toMatchObject({ step: 1, steps: 1, overall: 0.5 })
  })

  it('valori fuori scala restano fra 0 e 1', () => {
    expect(phaseProgress(pipeline({ phase: 'rewrite', current: 15, total: 12 })).phaseFraction).toBe(1)
  })
})
