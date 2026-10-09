/** Dove mettere un suggerimento rispetto al suo controllo, tenendolo dentro la finestra. */
const GAP = 8
const MARGIN = 8

export type TooltipSide = 'top' | 'right' | 'bottom'

/** Posizione della bolla: il lato chiesto se ci sta, altrimenti l'opposto; poi dentro la finestra. */
export function placeTooltip(
  r: { top: number; bottom: number; left: number; right: number; width: number; height: number },
  size: { width: number; height: number },
  side: TooltipSide,
  viewport: { width: number; height: number },
): { top: number; left: number } {
  const clamp = (value: number, max: number) => Math.max(MARGIN, Math.min(value, max - MARGIN))
  if (side === 'right') {
    const fitsRight = r.right + GAP + size.width <= viewport.width - MARGIN
    const fitsLeft = r.left - GAP - size.width >= MARGIN
    const left = fitsRight || !fitsLeft ? r.right + GAP : r.left - GAP - size.width
    return { top: clamp(r.top + r.height / 2 - size.height / 2, viewport.height - size.height), left: clamp(left, viewport.width - size.width) }
  }
  const above = r.top - GAP - size.height
  const below = r.bottom + GAP
  const fitsAbove = above >= MARGIN
  const fitsBelow = below + size.height <= viewport.height - MARGIN
  const top = side === 'top' ? (fitsAbove || !fitsBelow ? above : below) : (fitsBelow || !fitsAbove ? below : above)
  return { top: clamp(top, viewport.height - size.height), left: clamp(r.left + r.width / 2 - size.width / 2, viewport.width - size.width) }
}
