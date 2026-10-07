import type { RecallType } from '@/api/recall'

export const QUESTION_TYPE_LABELS: Record<RecallType, string> = {
  quiz: 'Quiz', mirata: 'Mirata', vasta: 'Vasta', caso: 'Caso clinico', esercizio: 'Esercizio',
}
export const advisedLabel = (type?: RecallType | null) => `Consigliato${type ? ` · ${QUESTION_TYPE_LABELS[type]}` : ''}`

/** A parità di conteggio si usa l'ordine dei tipi dell'interfaccia. */
export function mostSuggested(units: { suggested_qtype?: RecallType | null }[]) {
  const counts = new Map<RecallType, number>()
  for (const unit of units) if (unit.suggested_qtype) counts.set(unit.suggested_qtype, (counts.get(unit.suggested_qtype) ?? 0) + 1)
  const type = (Object.keys(QUESTION_TYPE_LABELS) as RecallType[]).reduce((best, next) => (counts.get(next) ?? 0) > (counts.get(best) ?? 0) ? next : best, 'quiz')
  return { type, count: counts.get(type) ?? 0, total: units.length }
}
