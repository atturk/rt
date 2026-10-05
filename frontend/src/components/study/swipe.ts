export type SwipeDirection = 'next' | 'prev'

export interface SwipePoints {
  startX: number
  startY: number
  startTime: number
  endX: number
  endY: number
  endTime: number
}

export interface SwipeOptions {
  minDistance?: number
  maxDuration?: number
  edgeThreshold?: number
  startInEdge?: boolean
  hasSelection?: boolean
  inScrollable?: boolean
}

/**
 * Riconosce se un gesto touch è uno swipe orizzontale valido per cambiare unità.
 * Soglie:
 * - |dx| >= 60
 * - |dx| > 2 * |dy|
 * - durata <= 600 ms
 * Guardie:
 * - non parte nei primi 25 px da sinistra (edge back iOS Safari)
 * - nessuna selezione di testo in corso
 * - non parte dentro elementi che scorrono in orizzontale
 * Direzioni:
 * - destra -> sinistra (dx < 0): 'next' (unità successiva)
 * - sinistra -> destra (dx > 0): 'prev' (unità precedente)
 */
export function detectSwipe(
  points: SwipePoints,
  options?: SwipeOptions,
): SwipeDirection | null {
  const minDistance = options?.minDistance ?? 60
  const maxDuration = options?.maxDuration ?? 600
  const edgeThreshold = options?.edgeThreshold ?? 25

  if (options?.startInEdge ?? points.startX <= edgeThreshold) {
    return null
  }
  if (options?.hasSelection) {
    return null
  }
  if (options?.inScrollable) {
    return null
  }

  const duration = points.endTime - points.startTime
  if (duration > maxDuration || duration < 0) {
    return null
  }

  const dx = points.endX - points.startX
  const dy = points.endY - points.startY

  if (Math.abs(dx) < minDistance) {
    return null
  }

  if (Math.abs(dx) <= 2 * Math.abs(dy)) {
    return null
  }

  return dx < 0 ? 'next' : 'prev'
}

/**
 * Controlla se l'elemento toccato o uno dei suoi antenati ha scorrimento orizzontale
 * (tabelle, blocchi di codice, formule con overflow-x: auto o scroll).
 */
export function isElementScrollableX(element: Element | null, container?: Element | null): boolean {
  let curr = element
  while (curr && curr !== container && curr !== document.body && curr !== document.documentElement) {
    if (curr instanceof HTMLElement) {
      const style = window.getComputedStyle(curr)
      if (
        (style.overflowX === 'auto' || style.overflowX === 'scroll') &&
        curr.scrollWidth > curr.clientWidth
      ) {
        return true
      }
      if (curr.tagName === 'TABLE' || curr.tagName === 'PRE') {
        if (curr.scrollWidth > curr.clientWidth) return true
      }
    }
    curr = curr.parentElement
  }
  return false
}
