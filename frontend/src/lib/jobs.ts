import type { Schemas } from '@/api/client'
import { PHASE_LABELS, type Tone } from '@/lib/format'

export type Job = Schemas['Job']
export type JobEvent = Schemas['JobEvent']

export const JOB_TYPE_LABELS: Record<string, string> = {
  run_pipeline: 'Pipeline completa',
  ingest_audio: 'Importazione audio',
  run_phase: 'Fase singola',
  rewrite_unit: 'Rielaborazione di una unità',
  outline_revision: 'Revisione della scaletta',
  add_images: 'Immagini',
  recall_generate: 'Domande di recall',
  recall_batch: 'Domande di recall',
  recall_refill: 'Rifornimento domande',
  recall_evaluate: 'Valutazione risposta',
  transcribe_voice: 'Trascrizione vocale',
  credential_test: 'Prova credenziale',
}

export const JOB_STATE_LABELS: Record<string, string> = {
  queued: 'In coda',
  running: 'In esecuzione',
  waiting_for_decision: 'Serve la tua decisione',
  succeeded: 'Completato',
  failed: 'Fallito',
  cancelled: 'Annullato',
}

export const ACTIVE_STATES = ['queued', 'running'] as const
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

export function isActive(state: string | undefined): boolean {
  return state === 'queued' || state === 'running'
}

export function isTerminal(state: string | undefined): boolean {
  return TERMINAL.has(state ?? '')
}

export function jobStateTone(state: string | undefined): Tone {
  switch (state) {
    case 'succeeded':
      return 'success'
    case 'failed':
      return 'danger'
    case 'waiting_for_decision':
      return 'warning'
    default:
      return 'neutral'
  }
}

export function jobTypeLabel(job: Pick<Job, 'type' | 'payload'>): string {
  if (job.type === 'run_phase') {
    const phase = String(job.payload?.phase ?? '')
    return `Fase: ${PHASE_LABELS[phase] ?? phase}`
  }
  return JOB_TYPE_LABELS[job.type] ?? job.type
}

const DECISION_LABELS: Record<string, string> = {
  outline_approval: 'approvare la scaletta',
  science_issue: 'valutare le issue della review',
  setup_metadata: 'completare i dati della lezione',
}

/** Cosa aspetta un job in waiting_for_decision, in parole. */
export function decisionLabel(decision: Job['decision']): string {
  const kind = String(decision?.kind ?? '')
  return DECISION_LABELS[kind] ?? 'prendere una decisione'
}

/** Pagina dove prendere la decisione attesa dal job. */
export function decisionLink(job: Pick<Job, 'decision' | 'lesson_id'>): string | null {
  if (job.lesson_id == null) return null
  return job.decision?.kind === 'outline_approval' ? `/lezioni/${job.lesson_id}/outline` : `/lezioni/${job.lesson_id}`
}

function phaseName(payload: Record<string, unknown>): string {
  const phase = String(payload.phase ?? '')
  return PHASE_LABELS[phase] ?? (phase === 'setup' ? 'Trascrizione e setup' : phase)
}

/** Riga leggibile per un evento del job (stream SSE o elenco). */
export function describeEvent(event: Pick<JobEvent, 'type' | 'payload'>): { text: string; tone: Tone } {
  const p = (event.payload ?? {}) as Record<string, unknown>
  switch (event.type) {
    case 'job_queued':
      return { text: p.retry_of ? 'In coda (nuovo tentativo di un job fallito)' : 'In coda', tone: 'neutral' }
    case 'job_started':
      return { text: Number(p.attempt ?? 1) > 1 ? `Avviato (tentativo ${p.attempt})` : 'Avviato dal worker', tone: 'neutral' }
    case 'job_requeued':
      return { text: 'Rimesso in coda', tone: 'neutral' }
    case 'job_resumed':
      return { text: 'Decisione presa: la pipeline riparte', tone: 'success' }
    case 'job_cancel_requested':
      return { text: 'Annullamento richiesto', tone: 'warning' }
    case 'job_waiting':
      return { text: 'In attesa di una tua decisione', tone: 'warning' }
    case 'job_finished': {
      const state = String(p.state ?? '')
      const text = JOB_STATE_LABELS[state] ?? state
      return { text: p.error ? `${text}: ${p.error}` : text, tone: jobStateTone(state) }
    }
    case 'phase_started': {
      const step = p.step && p.total_steps ? ` (${p.step}/${p.total_steps})` : ''
      return { text: `${phaseName(p)}: avviata${step}`, tone: 'neutral' }
    }
    case 'phase_progress': {
      const count = p.current != null && p.total ? ` ${p.current}/${p.total}` : ''
      return { text: `${phaseName(p)}:${count} ${String(p.message ?? '')}`.trim(), tone: 'neutral' }
    }
    case 'phase_completed': {
      if (p.partial) {
        const r = (p.result ?? {}) as Record<string, unknown>
        const count = r.completed_units != null && r.expected_units ? ` (${r.completed_units}/${r.expected_units} unità)` : ''
        return { text: `${phaseName(p)}: parziale${count}`, tone: 'warning' }
      }
      return { text: `${phaseName(p)}: ${p.skipped ? 'già aggiornata' : 'completata'}`, tone: 'success' }
    }
    case 'phase_failed':
      return { text: `${phaseName(p)}: errore. ${String(p.message ?? '')}`.trim(), tone: 'danger' }
    case 'cost_updated':
      return { text: `Costo stimato: $${Number(p.total_estimated_cost_usd ?? 0).toFixed(2)}`, tone: 'neutral' }
    case 'decision_required':
      return { text: `Serve la tua decisione: ${decisionLabel(p as Job['decision'])}`, tone: 'warning' }
    case 'notice':
      return { text: String(p.message ?? ''), tone: p.level === 'error' ? 'danger' : p.level === 'warning' ? 'warning' : 'neutral' }
    default:
      return { text: event.type, tone: 'neutral' }
  }
}

/**
 * Etichetta dell'avanzamento dai dati strutturati di jobs.progress (evento phase_progress):
 * fase e, nelle fasi a unità, unità in lavorazione sul totale ("Revisione · 8/31"), poi
 * l'unità e le eventuali unità fallite. Mai dedotta dal testo del messaggio.
 */
export function progressLabel(progress: Job['progress']): { phase: string | null; count: string | null; detail: string | null } {
  if (!progress) return { phase: null, count: null, detail: null }
  const p = progress as Record<string, unknown>
  const phase = typeof p.phase === 'string' ? (PHASE_LABELS[p.phase] ?? (p.phase === 'setup' ? 'Trascrizione e setup' : p.phase)) : null
  const current = Number(p.current)
  const total = Number(p.total)
  const count = Number.isFinite(current) && Number.isFinite(total) && total > 0 && !p.completed ? `${current}/${total}` : null
  const unit = typeof p.unit_id === 'string' ? [p.unit_id, typeof p.unit_title === 'string' ? p.unit_title : null].filter(Boolean).join(' ') : null
  const failed = Number(p.failed)
  const parts = [unit ?? (typeof p.message === 'string' && p.message ? p.message : null)]
  if (Number.isFinite(failed) && failed > 0) parts.push(failed === 1 ? '1 unità non riuscita' : `${failed} unità non riuscite`)
  const detail = parts.filter(Boolean).join(' · ') || null
  return { phase, count, detail }
}

/** "Revisione · 8/31" (fase e unità sul totale), per la riga sopra la barra. */
export function progressTitle(progress: Job['progress']): string | null {
  const { phase, count } = progressLabel(progress)
  return [phase, count].filter(Boolean).join(' · ') || null
}

/** Avanzamento del job (0-100) dalla colonna progress, se c'è. */
export function progressPercent(progress: Job['progress']): number | null {
  if (!progress) return null
  const current = Number(progress.current)
  const total = Number(progress.total)
  if (Number.isFinite(current) && Number.isFinite(total) && total > 0) return Math.min(100, Math.round((current / total) * 100))
  const step = Number(progress.step)
  const steps = Number(progress.total_steps)
  if (Number.isFinite(step) && Number.isFinite(steps) && steps > 0) {
    const done = progress.completed ? step : step - 1
    return Math.min(100, Math.max(0, Math.round((done / steps) * 100)))
  }
  return null
}

export const AUDIO_EXTENSIONS = ['.m4a', '.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4b', '.wma']

/** Controllo prima dell'upload: l'API rifiuta comunque (415/413) con un messaggio suo. */
export function audioFileProblem(files: { name: string; size: number }[]): string | null {
  if (files.length === 0) return 'Scegli almeno un file audio.'
  for (const file of files) {
    const dot = file.name.lastIndexOf('.')
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
    if (!AUDIO_EXTENSIONS.includes(ext)) return `Formato non supportato: ${file.name}. Usa ${AUDIO_EXTENSIONS.join(', ')}.`
    if (file.size === 0) return `Il file ${file.name} è vuoto.`
  }
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/** Aggiunge eventi nuovi evitando duplicati (lo stream può ripetere dopo una ripresa). */
export function mergeEvents(current: JobEvent[], incoming: JobEvent[]): JobEvent[] {
  const seen = new Set(current.map((e) => e.id))
  const fresh = incoming.filter((e) => !seen.has(e.id))
  if (fresh.length === 0) return current
  return [...current, ...fresh].sort((a, b) => a.id - b.id)
}
