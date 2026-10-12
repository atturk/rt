import { QUESTION_TYPE_LABELS } from '@/lib/questionTypes'
import { ThumbsDown, ThumbsUp, Zap } from 'lucide-react'

import { BASE_RECALL_TYPES, type RecallQuestion, type RecallType, type RecallTypeInfo, type Vote } from '@/api/recall'
import type { SlideOption } from '@/components/ui/slide-toggle'

export const RECALL_TYPES: { value: RecallType; label: string; hint: string }[] = [
  { value: 'quiz', label: QUESTION_TYPE_LABELS.quiz, hint: 'Scelta multipla, esito immediato' },
  { value: 'mirata', label: QUESTION_TYPE_LABELS.mirata, hint: 'Domanda aperta su un punto preciso' },
  { value: 'vasta', label: QUESTION_TYPE_LABELS.vasta, hint: 'Domanda aperta di collegamento' },
]
export const TYPE_OPTIONS: SlideOption<RecallType>[] = RECALL_TYPES.map((t) => ({ value: t.value, label: t.label }))
export const VOTES: { value: Vote; label: string; icon: typeof ThumbsUp }[] = [
  { value: 'up', label: 'Domanda utile', icon: ThumbsUp },
  { value: 'down', label: 'Domanda da scartare', icon: ThumbsDown },
  { value: 'lightning', label: 'Domanda fulminante', icon: Zap },
]

export function typeLabel(type: string, types: RecallTypeInfo[] = BASE_RECALL_TYPES) {
  return types.find(t => t.id === type)?.nome ?? "Tipo eliminato"
}

export function questionTypeId(question: Pick<RecallQuestion, "type" | "custom_type">) {
  return question.type === "personalizzata" ? question.custom_type ?? "_deleted" : question.type
}

/** Tipo di domanda da ?tipo= (quiz se manca o non è valido). */
export function recallTypeParam(value: string | null, types: RecallTypeInfo[] = BASE_RECALL_TYPES): RecallType {
  return types.some(t => t.id === value) ? value! : 'quiz'
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
