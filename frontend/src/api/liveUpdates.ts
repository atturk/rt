/**
 * Canale live della web app: un solo stream SSE (GET /api/v1/events) per tutta la pagina, aperto
 * dal layout dopo l'accesso. Ogni evento di un job dice quale job, di che tipo e su quale
 * lezione; qui si invalidano le query interessate e TanStack Query rilegge dall'API solo quelle
 * mostrate. Al posto dei refetchInterval sparsi: restano solo i controlli su dati che non
 * passano dai job (worker, bot Telegram, sessioni di recall, forma d'onda), ognuno commentato.
 */
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { useEffect } from 'react'

import { lessonKeys, queryKeys, reviewKeys } from './hooks'
import type { paths } from './schema'

const EVENTS_PATH = '/api/v1/events' satisfies keyof paths

/** Evento 'job' dello stream: solo chi e cosa, il resto si rilegge dall'API. */
export type LiveJobEvent = { id: number; job_id: string; job_type: string; lesson_id: number | null; type: string }

/** Eventi frequenti: il documento si rilegge solo per i job che scrivono checkpoint. */
const PROGRESS_EVENTS = new Set(['phase_progress', 'cost_updated', 'notice', 'job_cancel_requested', 'review_units_queued'])
/** Eventi dopo cui documento, fasi e issue della lezione possono essere cambiati. */
const LESSON_EVENTS = new Set(['phase_completed', 'phase_failed', 'job_waiting', 'job_finished', 'decision_required'])
const RECALL_JOBS = new Set(['recall_generate', 'recall_batch', 'recall_refill', 'recall_evaluate', 'unit_relevance'])
const DOCUMENT_JOBS = new Set(['run_pipeline', 'run_phase', 'rewrite_unit'])

const isLessonJobs = (key: QueryKey) => key[0] === 'lesson' && key[2] === 'jobs'

/** Query da rileggere per un evento. Le chiavi sono prefissi (come in invalidateQueries). */
export function keysForEvent(event: LiveJobEvent): QueryKey[] {
  const lesson = event.lesson_id
  // Stato e avanzamento del job: elenchi, dettaglio (jobs.ts, jobStatus.ts e settings.ts) e job della lezione.
  const keys: QueryKey[] = [['jobs'], ['job', event.job_id]]
  if (lesson != null) keys.push(lessonKeys.jobs(lesson))
  if (event.job_type === 'documents') {
    if (lesson != null && LESSON_EVENTS.has(event.type)) {
      keys.push(queryKeys.allLessons, queryKeys.lesson(lesson), lessonKeys.phases(lesson), lessonKeys.document(lesson))
    }
    return keys
  }
  if (lesson != null && event.type === 'review_unit_done') {
    keys.push(reviewKeys.issues(lesson), reviewKeys.units(lesson))
    return keys
  }
  if (event.job_type.startsWith('enrichment_')) keys.push(['enrichment'])
  if (event.type === 'cost_updated') keys.push(queryKeys.costs)
  if (lesson != null && event.type === 'phase_progress' && DOCUMENT_JOBS.has(event.job_type)) keys.push(lessonKeys.document(lesson))
  if (PROGRESS_EVENTS.has(event.type)) return keys

  keys.push(queryKeys.allLessons, ['enrichment'])
  if (lesson != null) {
    keys.push(LESSON_EVENTS.has(event.type) ? lessonKeys.all(lesson) : queryKeys.lesson(lesson), lessonKeys.phases(lesson))
    keys.push(['outline', lesson])
    if (event.job_type === 'add_images') keys.push(['images', lesson])
    if (event.job_type === 'unit_relevance') keys.push(['relevance', lesson])
  }
  if (RECALL_JOBS.has(event.job_type)) keys.push(['recall'], ['recall-subject'])
  if (LESSON_EVENTS.has(event.type)) keys.push(queryKeys.costs)
  return keys
}

/** Quello che gli eventi aggiornerebbero: si rilegge all'apertura dello stream e, se è giù, ogni tanto. */
function invalidateJobQueries(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ['jobs'] })
  void client.invalidateQueries({ queryKey: ['job'] })
  void client.invalidateQueries({ predicate: (query) => isLessonJobs(query.queryKey) })
  void client.invalidateQueries({ queryKey: ['enrichment'] })
  // I checkpoint prodotti durante una disconnessione devono comparire anche senza un evento nuovo.
  void client.invalidateQueries({ predicate: (query) => query.queryKey[0] === 'lesson' && query.queryKey[2] === 'document' })
  void client.invalidateQueries({ queryKey: ['outline'] })
  void client.invalidateQueries({ queryKey: ['recall-subject'] })
}

/** Gli eventi arrivano a raffiche (una per unità): si invalida al massimo ogni FLUSH_MS. */
const FLUSH_MS = 300
/** Riconnessione dopo un errore che chiude lo stream (es. API ferma): attesa che raddoppia fino a MAX. */
const RETRY_MIN_MS = 1_000
const RETRY_MAX_MS = 30_000
/** Ripiego mentre lo stream è giù: si rilegge comunque lo stato dei job ogni FALLBACK_MS. */
const FALLBACK_MS = 10_000

/**
 * Apre il canale live (una volta, nel layout) finché `enabled`. Il browser si riconnette da
 * solo dopo una caduta di rete, con Last-Event-ID; se lo stream si chiude per un errore (API
 * ferma, 401, 503) lo riapre questo hook con attesa crescente, da dopo l'ultimo evento ricevuto.
 * Autenticazione come lo stream dei job: il cookie di sessione (withCredentials).
 */
export function useLiveUpdates(enabled: boolean) {
  const client = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    let source: EventSource | null = null
    let lastId: string | null = null
    let retryMs = RETRY_MIN_MS
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let flushTimer: ReturnType<typeof setTimeout> | undefined
    let fallback: ReturnType<typeof setInterval> | undefined
    const pending = new Map<string, QueryKey>()

    const flush = () => {
      flushTimer = undefined
      for (const queryKey of pending.values()) void client.invalidateQueries({ queryKey })
      pending.clear()
    }
    const startFallback = () => {
      fallback ??= setInterval(() => invalidateJobQueries(client), FALLBACK_MS)
    }
    const stopFallback = () => {
      clearInterval(fallback)
      fallback = undefined
    }

    const connect = () => {
      // Senza EventSource (es. jsdom nei test) resta solo il ripiego.
      if (typeof EventSource === 'undefined') return startFallback()
      const url = lastId === null ? EVENTS_PATH : `${EVENTS_PATH}?after=${encodeURIComponent(lastId)}`
      const es = new EventSource(url, { withCredentials: true })
      source = es
      es.onopen = () => {
        retryMs = RETRY_MIN_MS
        stopFallback()
        // Quello che è successo prima dello stream (o mentre era giù) si rilegge una volta.
        invalidateJobQueries(client)
      }
      es.addEventListener('job', (message: MessageEvent<string>) => {
        lastId = message.lastEventId || lastId
        for (const key of keysForEvent(JSON.parse(message.data) as LiveJobEvent)) pending.set(JSON.stringify(key), key)
        flushTimer ??= setTimeout(flush, FLUSH_MS)
      })
      es.onerror = () => {
        startFallback()
        if (es.readyState !== EventSource.CLOSED) return // si riconnette il browser
        es.close()
        retryTimer = setTimeout(connect, retryMs)
        retryMs = Math.min(retryMs * 2, RETRY_MAX_MS)
      }
    }

    connect()
    return () => {
      source?.close()
      clearTimeout(retryTimer)
      clearTimeout(flushTimer)
      stopFallback()
    }
  }, [client, enabled])
}
