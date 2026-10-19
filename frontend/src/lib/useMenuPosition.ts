import { useLayoutEffect, useState, type CSSProperties, type RefObject } from 'react'

/** Il menu segue il pulsante anche nei pannelli scorrevoli, fuori dai loro ritagli. */
export function useMenuPosition(open: boolean, root: RefObject<HTMLDivElement | null>, menu: RefObject<HTMLDivElement | null>, side: 'top' | 'bottom' = 'bottom') {
  const [style, setStyle] = useState<CSSProperties>({ visibility: 'hidden' })
  const [host, setHost] = useState<Element>(document.body)
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      setHost(root.current?.closest('dialog') ?? document.body)
      const button = root.current?.querySelector('button[aria-haspopup]')
      const bubble = menu.current
      if (!button || !bubble) return
      const anchor = button.getBoundingClientRect()
      const width = bubble.offsetWidth
      const height = bubble.offsetHeight
      const margin = 8
      const above = anchor.top - 6 - height
      const below = anchor.bottom + 6
      const fitsAbove = above >= margin
      const fitsBelow = below + height <= window.innerHeight - margin
      const top = side === 'top' ? (fitsAbove || !fitsBelow ? above : below) : (fitsBelow || !fitsAbove ? below : above)
      setStyle({
        top: Math.max(margin, Math.min(top, window.innerHeight - height - margin)),
        left: Math.max(margin, Math.min(anchor.right - width, window.innerWidth - width - margin)),
      })
    }
    place()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place)
    if (menu.current) observer?.observe(menu.current)
    window.addEventListener('resize', place)
    document.addEventListener('scroll', place, true)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', place)
      document.removeEventListener('scroll', place, true)
    }
  }, [open, root, menu, side, host])
  return { style, host }
}

