import * as React from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/utils'

// Un solo suggerimento aperto; il gruppo resta caldo per 300 ms dopo la chiusura.
let activeTooltip: (() => void) | null = null
let lastClosed: number | null = null

const canHover = () => !window.matchMedia?.('(hover: none)').matches

type Side = 'top' | 'right' | 'bottom'

export type TooltipTriggerProps = {
  ref: React.RefCallback<HTMLElement>
  'aria-describedby'?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onFocus: () => void
  onBlur: () => void
  onPointerDown: () => void
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

  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const suppressed = React.useRef(false)
  const hide = React.useCallback(function hideTooltip() {
    clearTimeout(timer.current)
    timer.current = undefined
    if (activeTooltip === hideTooltip) {
      activeTooltip = null
      lastClosed = Date.now()
    }
    setOpen(false)
  }, [])
  React.useEffect(() => hide, [hide])

  const show = React.useCallback(() => {
    if (!trigger || disabled || suppressed.current || !canHover()) return
    if (activeTooltip !== hide) activeTooltip?.()
    activeTooltip = hide
    const r = trigger.getBoundingClientRect()
    const gap = 8
    if (side === 'right') setPos({ top: r.top + r.height / 2, left: r.right + gap })
    else if (side === 'bottom') setPos({ top: r.bottom + gap, left: r.left + r.width / 2 })
    else setPos({ top: r.top - gap, left: r.left + r.width / 2 })
    setOpen(true)
  }, [side, trigger, disabled, hide])
  const hover = React.useCallback(() => {
    suppressed.current = false
    if (!canHover() || disabled) return
    clearTimeout(timer.current)
    if (activeTooltip || (lastClosed !== null && Date.now() - lastClosed < 300)) show()
    else timer.current = setTimeout(show, 600)
  }, [disabled, show])

  const focus = React.useCallback(() => { if (trigger?.matches(':focus-visible')) show() }, [trigger, show])
  const pointerDown = React.useCallback(() => { suppressed.current = true; hide() }, [hide])
  const visible = open && !disabled && pos !== null
  const props: TooltipTriggerProps = {
    ref: setTrigger,
    'aria-describedby': describe && !disabled ? id : undefined,
    onMouseEnter: hover,
    onMouseLeave: hide,
    onFocus: focus,
    onPointerDown: pointerDown,
    onBlur: hide,
    onKeyDown: (e) => {
      // Solo se il suggerimento si vede: altrimenti Esc va a chi lo aspetta (menu, dialoghi).
      if (e.key === 'Escape' && visible) {
        e.stopPropagation()
        hide()
      }
    },
  }
  const transform =
    side === 'right' ? 'translateY(-50%)' : side === 'bottom' ? 'translateX(-50%)' : 'translate(-50%, -100%)'
  return (
    <>
      {/* oxlint-disable-next-line react/refs -- Il render-prop passa i gestori al trigger; i ref si leggono solo negli eventi. */}
      {children(props)}
      {/* Sempre nel DOM per aria-describedby; visibile solo quando aperto. */}
      {createPortal(
        <div
          id={id}
          role="tooltip"
          hidden={!visible}
          style={pos ? { top: pos.top, left: pos.left, transform } : undefined}
          className={cn(
            'pointer-events-none fixed z-[60] max-w-72 rounded-md bg-foreground px-2 py-1 text-xs leading-snug text-background shadow-lg',
          )}
        >
          {content}
        </div>,
        // Dentro un <dialog> modale il suggerimento sta nel dialog: il resto della pagina è sotto.
        trigger?.closest('dialog') ?? document.body,
      )}
    </>
  )
}
