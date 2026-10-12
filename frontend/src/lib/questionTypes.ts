import { BASE_RECALL_TYPES, type RecallTypeInfo, type RecallType } from '@/api/recall'

export const QUESTION_TYPE_LABELS: Record<RecallType, string> = {
  quiz: 'Quiz', mirata: 'Mirata', vasta: 'Vasta',
}
export const advisedLabel = (type?: RecallType | null, types = BASE_RECALL_TYPES) => `Consigliato${type ? ` · ${types.find(t => t.id === type)?.nome ?? 'Tipo eliminato'}` : ''}`

/** A parità di conteggio si usa l'ordine dei tipi dell'interfaccia. */
export function mostSuggested(units: { suggested_qtype?: RecallType | null }[], types: RecallTypeInfo[] = BASE_RECALL_TYPES) {
  const counts = new Map<RecallType, number>()
  for (const unit of units) if (unit.suggested_qtype) counts.set(unit.suggested_qtype, (counts.get(unit.suggested_qtype) ?? 0) + 1)
  const type = types.map(t => t.id).reduce((best, next) => (counts.get(next) ?? 0) > (counts.get(best) ?? 0) ? next : best, 'quiz')
  return { type, count: counts.get(type) ?? 0, total: units.length }
}

export function unitsAdviceBreakdown(
  units: { suggested_qtype?: RecallType | null }[],
  types: RecallTypeInfo[] = BASE_RECALL_TYPES,
): string {
  const counts = new Map<string, number>()
  for (const unit of units) {
    const q = unit.suggested_qtype ?? 'quiz'
    counts.set(q, (counts.get(q) ?? 0) + 1)
  }
  const parts: string[] = []
  for (const t of types) {
    const c = counts.get(t.id)
    if (c) parts.push(`${c} ${t.nome}`)
  }
  for (const [id, c] of counts.entries()) {
    if (!types.some((t) => t.id === id)) {
      parts.push(`${c} ${id}`)
    }
  }
  if (parts.length === 0) return 'Ogni unità riceve il tipo che Jev le ha consigliato.'
  if (parts.length === 1) return `Ogni unità riceve il tipo che Jev le ha consigliato: qui ${parts[0]}.`
  return `Ogni unità riceve il tipo che Jev le ha consigliato: qui ${parts.slice(0, -1).join(', ')} e ${parts[parts.length - 1]}.`
}
