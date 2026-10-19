import type { CSSProperties } from 'react'
import type { PopupAnchor } from './CalendarPopups'

export function computePopupStyle(anchor: PopupAnchor, width = 270): CSSProperties {
  const pad = 12
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1000
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800

  let left = anchor.x + anchor.width + 8
  if (left + width > vw - pad) {
    left = anchor.x - width - 8
  }
  if (left < pad) {
    left = pad
  }

  let top = anchor.y
  if (top + 320 > vh - pad) {
    top = Math.max(pad, vh - 330)
  }

  return {
    position: 'fixed',
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    zIndex: 60,
  }
}

