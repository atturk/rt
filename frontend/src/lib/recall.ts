import { QUESTION_TYPE_LABELS } from '@/lib/questionTypes'
import { ThumbsDown, ThumbsUp, Zap } from 'lucide-react'

import type { RecallType, Vote } from '@/api/recall'
import type { SlideOption } from '@/components/ui/slide-toggle'

export const RECALL_TYPES: { value: RecallType; label: string; hint: string }[] = [
  { value: 'quiz', label: QUESTION_TYPE_LABELS.quiz, hint: 'Scelta multipla, esito immediato' },
  { value: 'mirata', label: QUESTION_TYPE_LABELS.mirata, hint: 'Domanda aperta su un punto preciso' },
  { value: 'vasta', label: QUESTION_TYPE_LABELS.vasta, hint: 'Domanda aperta di collegamento' },
  { value: 'caso', label: QUESTION_TYPE_LABELS.caso, hint: 'Caso clinico da ragionare, dalle unità che lo contengono' },
  { value: 'esercizio', label: QUESTION_TYPE_LABELS.esercizio, hint: 'Esercizio da svolgere, dalle unità in cui viene risolto' },
]
export const TYPE_OPTIONS: SlideOption<RecallType>[] = RECALL_TYPES.map((t) => ({ value: t.value, label: t.label }))
export const VOTES: { value: Vote; label: string; icon: typeof ThumbsUp }[] = [
  { value: 'up', label: 'Domanda utile', icon: ThumbsUp },
  { value: 'down', label: 'Domanda da scartare', icon: ThumbsDown },
  { value: 'lightning', label: 'Domanda fulminante', icon: Zap },
]

export function typeLabel(type: string) {
  return RECALL_TYPES.find((t) => t.value === type)?.label ?? type
}

/** Tipo di domanda da ?tipo= (quiz se manca o non è valido). */
export function recallTypeParam(value: string | null): RecallType {
  return RECALL_TYPES.some((t) => t.value === value) ? (value as RecallType) : 'quiz'
}

export function startedAt(iso: string) {
  return new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

/** Domande per tipo e stato (come GET /lessons/{id}/recall): quante ce ne sono in uno stato. */
export function countStatus(questions: Record<string, Record<string, number>> | undefined, status: string, type?: string): number {
  return Object.entries(questions ?? {})
    .filter(([t]) => !type || t === type)
    .reduce((sum, [, byStatus]) => sum + (byStatus[status] ?? 0), 0)
}
