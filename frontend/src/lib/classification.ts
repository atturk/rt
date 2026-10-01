import type { Schemas } from '@/api/client'

/**
 * Se il classificatore è passato su una lezione, detto in breve per elenchi e avvisi (pagina
 * del recall, lezione). Il recall usa le sue etichette per orientare le domande: una lezione
 * non classificata va notata.
 */
export type ClassificationStatus = Schemas['ClassificationStatus']
type Tone = 'neutral' | 'success' | 'warning'

export function classificationLabel(status?: ClassificationStatus | null): { text: string; tone: Tone; pending: boolean } {
  switch (status?.state) {
    case 'done':
      return { text: 'Classificata', tone: 'success', pending: false }
    case 'partial':
      return { text: `Classificate ${status.classified}/${status.total} unità`, tone: 'warning', pending: true }
    case 'stale':
      return { text: 'Da riclassificare', tone: 'warning', pending: true }
    case 'never':
      return { text: 'Non classificata', tone: 'warning', pending: true }
    case 'running':
      return { text: 'Classificazione in corso', tone: 'neutral', pending: false }
    case 'disabled':
      return { text: 'Classificatore spento', tone: 'neutral', pending: false }
    default:
      return { text: '—', tone: 'neutral', pending: false }
  }
}

/** Stato dal riepilogo della pagina Classificatore (stesse regole di classification_status). */
export function statusFromSummary(mode: string, summary?: Schemas['UnitRelevanceSummary'] | null, units = 0): ClassificationStatus {
  if (mode === 'disabled') return { state: 'disabled', classified: 0, total: 0 }
  const total = summary?.total ?? units
  if (!summary || total === 0) return { state: 'unavailable', classified: 0, total }
  if (summary.classified === total) return { state: 'done', classified: total, total }
  if (summary.classified === 0 && summary.errors === 0) return { state: summary.stale > 0 ? 'stale' : 'never', classified: 0, total }
  return { state: 'partial', classified: summary.classified, total }
}

/** Testi dei due pulsanti del classificatore, con quello che fanno davvero. */
export const RUN_NEW = {
  label: 'Classifica solo le unità nuove o modificate',
  first: 'Classifica la lezione',
  title: 'Etichetta le unità mai classificate e quelle il cui testo (o la configurazione del classificatore) è cambiato. ' +
    'Le altre restano come sono.',
}
export const RUN_ALL = {
  label: 'Riclassifica tutte le unità',
  title: 'Ripete la classificazione su ogni unità, anche se già etichettata. Le etichette che hai corretto a mano restano.',
}
