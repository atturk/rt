import type { RecallType } from '@/api/recall'

export const QUESTION_TYPE_LABELS: Record<RecallType, string> = {
  quiz: 'Quiz', mirata: 'Mirata', vasta: 'Vasta', caso: 'Caso clinico', esercizio: 'Esercizio',
}
export const advisedLabel = (type?: RecallType | null) => `Consigliato${type ? ` · ${QUESTION_TYPE_LABELS[type]}` : ''}`
