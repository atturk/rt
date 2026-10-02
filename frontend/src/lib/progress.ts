import { PHASE_LABELS } from './format'
import { AUDIO_EXTENSIONS, type Job } from './jobs'

/**
 * Avanzamento a due barre (design 4.2, schermata 03): davanti il totale, dietro la fase in
 * corso. Il totale pesa ogni fase in modo uguale: (fasi finite + avanzamento della fase) / n.
 * Tutto si ricava da job.type, job.payload e job.progress (l'ultimo evento di fase salvato).
 */
export type PhaseProgress = {
  /** Nome della fase in corso ("Rielaborazione"), null se il job non è ancora partito. */
  phase: string | null
  /** Dettaglio della fase ("unità 10 di 12", "Trascrizione audio: 42%"). */
  detail: string | null
  /** Posizione della fase in corso, da 1. */
  step: number
  /** Numero di fasi del job. */
  steps: number
  /** Avanzamento della fase in corso, 0-1. */
  phaseFraction: number
  /** Avanzamento totale, 0-1. */
  overall: number
}

const UNIT_PHASES = new Set(['rewrite', 'review'])

function isAudio(path: unknown): boolean {
  const name = String(path ?? '').toLowerCase()
  return AUDIO_EXTENSIONS.some((ext) => name.endsWith(ext))
}

/** Fasi del job nell'ordine in cui le esegue la pipeline (rt/services/pipeline_service.py). */
export function jobPhases(job: Pick<Job, 'type' | 'payload'>): string[] {
  const payload = (job.payload ?? {}) as Record<string, unknown>
  const options = (payload.options ?? {}) as Record<string, unknown>
  switch (job.type) {
    case 'run_pipeline': {
      const inputs = Array.isArray(payload.inputs) ? payload.inputs : []
      return [
        ...(inputs.some(isAudio) ? ['setup'] : []),
        'prepare',
        'outline',
        'rewrite',
        ...(options.with_review ? ['review'] : []),
        'build',
      ]
    }
    case 'ingest_audio':
      return ['setup']
    case 'run_phase':
      return [String(payload.phase ?? 'phase')]
    case 'rewrite_unit':
      return ['rewrite']
    case 'review_unit':
      return ['review']
    default:
      return []
  }
}

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? (phase === 'setup' ? 'Trascrizione' : phase)
}

const clamp = (n: number) => Math.min(1, Math.max(0, n))

/** Stato delle due barre per un job. */
export function phaseProgress(job: Pick<Job, 'type' | 'payload' | 'progress' | 'state'>): PhaseProgress {
  const p = (job.progress ?? {}) as Record<string, unknown>
  const current = typeof p.phase === 'string' ? p.phase : null
  let phases = jobPhases(job)
  // Fase che l'elenco non prevede (job di altri tipi, es. le domande di recall): una fase sola.
  if (current && !phases.includes(current)) phases = [current]
  if (phases.length === 0) phases = ['job']
  const index = current ? phases.indexOf(current) : 0

  const done = Number(p.current)
  const total = Number(p.total)
  const counted = Number.isFinite(done) && Number.isFinite(total) && total > 0
  let fraction = p.completed ? 1 : counted ? clamp(done / total) : 0
  let detail: string | null = null
  if (!p.completed && counted) {
    if (current === 'setup') detail = typeof p.message === 'string' && p.message ? p.message : `${Math.round(fraction * 100)}%`
    else detail = UNIT_PHASES.has(current ?? '') ? `unità ${done} di ${total}` : `${done} di ${total}`
  } else if (!p.completed && typeof p.message === 'string' && p.message) detail = p.message

  if (job.state === 'succeeded') fraction = 1
  const overall = job.state === 'succeeded' ? 1 : clamp((index + fraction) / phases.length)
  return {
    phase: current ? phaseLabel(current) : null,
    detail,
    step: index + 1,
    steps: phases.length,
    phaseFraction: fraction,
    overall: job.state === 'queued' && !current ? 0 : overall,
  }
}

/** Testo a destra delle barre: "fase 4 di 6 · 64%". */
export function progressSummary(progress: PhaseProgress): string {
  const percent = `${Math.round(progress.overall * 100)}%`
  return progress.steps > 1 ? `fase ${progress.step} di ${progress.steps} · ${percent}` : percent
}
