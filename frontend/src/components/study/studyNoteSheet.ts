import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

type SheetLevel = 0 | 1 | 2
const readViewport = () => ({
  top: window.visualViewport?.offsetTop ?? 0,
  left: window.visualViewport?.offsetLeft ?? 0,
  width: window.visualViewport?.width ?? window.innerWidth,
  height: window.visualViewport?.height ?? window.innerHeight,
})

export function sheetHeights(height: number) {
  const full = Math.max(1, height - 12)
  return [Math.min(full, Math.max(200, full * .28)), Math.min(full, Math.max(200, full * .55)), full]
}

export function useStudyNoteSheet(open: boolean, phone: boolean, longAnswer: boolean) {
  const [viewport, setViewport] = useState(readViewport)
  const [level, setLevel] = useState<SheetLevel>(longAnswer ? 2 : 1)
  const [previous, setPrevious] = useState({ open, phone, longAnswer })
  if (previous.open !== open || previous.phone !== phone || previous.longAnswer !== longAnswer) {
    setPrevious({ open, phone, longAnswer })
    setLevel(longAnswer ? 2 : 1)
  }
  const gestureCleanup = useRef<(() => void) | null>(null)
  useEffect(() => () => { gestureCleanup.current?.() }, [open, phone])
  useEffect(() => {
    if (!open || !phone) return
    const update = () => setViewport(readViewport())
    update()
    const visual = window.visualViewport
    visual?.addEventListener('resize', update)
    visual?.addEventListener('scroll', update)
    window.addEventListener('resize', update)
    return () => { visual?.removeEventListener('resize', update); visual?.removeEventListener('scroll', update); window.removeEventListener('resize', update) }
  }, [open, phone])

  const heights = sheetHeights(viewport.height)
  const begin = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    const startY = event.clientY
    const move = (e: PointerEvent) => {
      const height = heights[level] + startY - e.clientY
      const nearest = heights.reduce((best, value, i) => Math.abs(value - height) < Math.abs(heights[best] - height) ? i : best, 0)
      setLevel(nearest as SheetLevel)
    }
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop) }
    gestureCleanup.current?.()
    gestureCleanup.current = stop
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
    window.addEventListener('pointercancel', stop, { once: true })
  }
  return {
    level, begin,
    step: (direction: number) => setLevel((current) => Math.max(0, Math.min(2, current + direction)) as SheetLevel),
    style: { left: viewport.left, width: viewport.width, top: viewport.top + viewport.height - heights[level], height: heights[level], maxHeight: viewport.height - 12 },
  }
}
