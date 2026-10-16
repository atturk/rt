import { useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

export type PopupFrame = { x: number; y: number; width: number; height: number | null; docked?: boolean }
type Viewport = { width: number; height: number }
let sessionFrame: PopupFrame | null = null

export function fitPopup(frame: PopupFrame, viewport: Viewport, measuredHeight = 240): PopupFrame {
  const margin = frame.docked ? 0 : 12
  const availableWidth = Math.max(1, viewport.width - margin * 2)
  const availableHeight = Math.max(1, viewport.height - margin * 2)
  const width = Math.min(Math.max(320, frame.width), availableWidth)
  const height = frame.docked ? availableHeight : frame.height === null ? null : Math.min(Math.max(240, frame.height), availableHeight)
  const occupiedHeight = height ?? Math.min(Math.max(240, measuredHeight), availableHeight)
  return { ...frame, width, height,
    x: frame.docked ? viewport.width - width : Math.max(margin, Math.min(frame.x, viewport.width - width - margin)),
    y: frame.docked ? 0 : Math.max(margin, Math.min(frame.y, viewport.height - occupiedHeight - margin)),
  }
}

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight })
const initialFrame = (anchor?: DOMRect | null): PopupFrame => ({
  x: (anchor ? anchor.left + anchor.width / 2 : window.innerWidth / 2) - 220,
  y: anchor ? anchor.bottom + 8 : 80, width: 440, height: null,
})

export function useStudyNoteWindow(open: boolean, phone: boolean, anchor?: DOMRect | null) {
  const ref = useRef<HTMLDivElement>(null)
  const [frame, setFrame] = useState<PopupFrame>(() => fitPopup(sessionFrame ?? initialFrame(anchor), viewport()))
  const measured = useRef(240)
  const adjusted = useRef(!!sessionFrame)
  const gestureCleanup = useRef<(() => void) | null>(null)

  useLayoutEffect(() => {
    if (!open || phone) return
    adjusted.current = !!sessionFrame
    setFrame(fitPopup(sessionFrame ?? initialFrame(anchor), viewport(), measured.current))
    const measure = () => {
      const height = ref.current?.getBoundingClientRect().height
      if (height) measured.current = height
      setFrame((previous) => {
        let next = previous
        if (!adjusted.current && anchor) {
          const top = anchor.bottom + 8
          next = { ...next, y: top + measured.current <= window.innerHeight - 12
            ? top : anchor.top - measured.current - 8 }
        }
        next = fitPopup(next, viewport(), measured.current)
        return JSON.stringify(next) === JSON.stringify(previous) ? previous : next
      })
    }
    measure()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    if (ref.current) observer?.observe(ref.current)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); gestureCleanup.current?.() }
  }, [open, phone, anchor])

  const remember = (next: PopupFrame) => {
    adjusted.current = true
    sessionFrame = fitPopup(next, viewport(), measured.current)
    setFrame(sessionFrame)
  }

  const begin = (event: ReactPointerEvent, edge = '') => {
    if (phone || frame.docked || event.button !== 0) return
    if (!edge && (event.target as HTMLElement).closest('button,a')) return
    event.preventDefault()
    const rect = ref.current?.getBoundingClientRect()
    const start = { ...frame, height: rect?.height || frame.height || measured.current }
    const x = event.clientX, y = event.clientY
    const move = (e: PointerEvent) => {
      const dx = e.clientX - x, dy = e.clientY - y
      if (!edge) { remember({ ...start, height: frame.height, x: start.x + dx, y: start.y + dy }); return }
      const next = { ...start }
      if (edge.includes('e')) next.width = Math.max(320, Math.min(window.innerWidth - 12 - start.x, start.width + dx))
      if (edge.includes('s')) next.height = Math.max(240, Math.min(window.innerHeight - 12 - start.y, start.height + dy))
      if (edge.includes('w')) { next.x = Math.max(12, Math.min(start.x + start.width - 320, start.x + dx)); next.width = start.x + start.width - next.x }
      if (edge.includes('n')) { next.y = Math.max(12, Math.min(start.y + start.height - 240, start.y + dy)); next.height = start.y + start.height - next.y }
      remember(next)
    }
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop) }
    gestureCleanup.current?.()
    gestureCleanup.current = stop
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  }

  const reset = () => { sessionFrame = null; adjusted.current = false; setFrame(fitPopup(initialFrame(anchor), viewport(), measured.current)) }
  const dock = () => frame.docked ? reset() : remember({ ...frame, width: 520, docked: true })
  return { ref, frame, begin, reset, dock }
}
