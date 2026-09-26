/**
 * Ordinamento delle issue nella colonna "Da decidere" della revisione. Modulo puro: riordina
 * solo quello che arriva dall'API, senza stato di dominio.
 */

export type IssueOrder = 'cronologico' | 'gravita'

export const ISSUE_ORDERS: { value: IssueOrder; label: string }[] = [
  { value: 'cronologico', label: 'Cronologico' },
  { value: 'gravita', label: 'Tipo e gravità' },
]

/** Tipi di issue dal più importante: prima gli errori concettuali, poi gli avvisi sull'unità. */
export const TYPE_RANK: readonly string[] = ['ERR_CONCETTUALE', 'ERR_REWRITE_DRIFT', 'ERR_ASR_LLM', 'ERR_ASR_ST']

/** Gravità dalla più alta. */
export const SEVERITY_RANK: readonly string[] = ['high', 'medium', 'low']

/** Ordine letto da ?ordine=: quello cronologico se manca o non è valido. */
export function parseIssueOrder(value: string | null | undefined): IssueOrder {
  return value === 'gravita' ? 'gravita' : 'cronologico'
}

export type SortableIssue = { type: string; severity: string; startSeconds?: number | null }

// Valori sconosciuti dopo quelli noti; tempi mancanti in fondo.
const rank = (list: readonly string[], value: string) => {
  const i = list.indexOf(value)
  return i < 0 ? list.length : i
}
const time = (s: number | null | undefined) => (s == null || !Number.isFinite(s) ? Infinity : s)

function compare(order: IssueOrder, a: SortableIssue, b: SortableIssue): number {
  if (order === 'gravita') {
    const byType = rank(TYPE_RANK, a.type) - rank(TYPE_RANK, b.type)
    if (byType) return byType
    const bySeverity = rank(SEVERITY_RANK, a.severity) - rank(SEVERITY_RANK, b.severity)
    if (bySeverity) return bySeverity
  }
  const at = time(a.startSeconds)
  const bt = time(b.startSeconds)
  return at === bt ? 0 : at < bt ? -1 : 1
}

/** Copia ordinata di `items`; a parità mantiene l'ordine dell'API (ordinamento stabile). */
export function sortIssues<T>(items: readonly T[], order: IssueOrder, key: (item: T) => SortableIssue): T[] {
  return items
    .map((item, index) => ({ item, index, k: key(item) }))
    .sort((a, b) => compare(order, a.k, b.k) || a.index - b.index)
    .map((e) => e.item)
}
