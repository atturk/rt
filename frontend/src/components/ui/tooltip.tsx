import * as React from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/utils'

type Side = 'top' | 'right' | 'bottom'

export type TooltipTriggerProps = {
  ref: React.RefCallback<HTMLElement>
  'aria-describedby'?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onFocus: () => void
  onBlur: () => void
  onKeyDown: (e: React.KeyboardEvent) => void
}

/**
 * Suggerimento che compare al passaggio del mouse e al focus da tastiera, si chiude con Esc
 * (WCAG 1.4.13) ed è sopra tutto (portale in document.body, posizione fissa dal trigger).
 * Il trigger riceve le props dal render-prop; `describe` collega il testo con aria-describedby
 * (da togliere quando il testo è già il nome accessibile del trigger).
 */
export function Tooltip({
  content,
  side = 'top',
  describe = true,
  disabled = false,
  children,
}: {
  content: React.ReactNode
  side?: Side
  describe?: boolean
  disabled?: boolean
  children: (props: TooltipTriggerProps) => React.ReactNode
}) {
  const id = React.useId()
  const [open, setOpen] = React.useState(false)
  const [pos, setPos] = React.useState<{ top: number; left: number } | null>(null)
  const [trigger, setTrigger] = React.useState<HTMLElement | null>(null)

  const show = React.useCallback(() => {
    if (!trigger) return
    const r = trigger.getBoundingClientRect()
    const gap = 8
    if (side === 'right') setPos({ top: r.top + r.height / 2, left: r.right + gap })
    else if (side === 'bottom') setPos({ top: r.bottom + gap, left: r.left + r.width / 2 })
    else setPos({ top: r.top - gap, left: r.left + r.width / 2 })
    setOpen(true)
  }, [side, trigger])
  const hide = React.useCallback(() => setOpen(false), [])

  const visible = open && !disabled && pos !== null
  const props: TooltipTriggerProps = {
    ref: setTrigger,
    'aria-describedby': describe && !disabled ? id : undefined,
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
    onKeyDown: (e) => {
      if (e.key === 'Escape' && open) {
        e.stopPropagation()
        hide()
      }
    },
  }
  const transform =
    side === 'right' ? 'translateY(-50%)' : side === 'bottom' ? 'translateX(-50%)' : 'translate(-50%, -100%)'
  return (
    <>
      {children(props)}
      {/* Sempre nel DOM per aria-describedby; visibile solo quando aperto. */}
      {createPortal(
        <div
          id={id}
          role="tooltip"
          hidden={!visible}
          style={pos ? { top: pos.top, left: pos.left, transform } : undefined}
          className={cn(
            'pointer-events-none fixed z-[60] max-w-72 rounded-md bg-primary px-2.5 py-1.5 text-xs leading-snug text-primary-foreground shadow-lg',
          )}
        >
          {content}
        </div>,
        document.body,
      )}
    </>
  )
}
