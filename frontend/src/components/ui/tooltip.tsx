import * as React from 'react'
import { createPortal } from 'react-dom'

import { placeTooltip, type TooltipSide } from '@/lib/tooltipPlacement'
import { cn } from '@/lib/utils'

// Un solo suggerimento aperto; il gruppo resta caldo per 300 ms dopo la chiusura.
let activeTooltip: (() => void) | null = null
let lastClosed: number | null = null

const canHover = () => !window.matchMedia?.('(hover: none)').matches

type Side = TooltipSide

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
  const [anchor, setAnchor] = React.useState<DOMRect | null>(null)
  const [pos, setPos] = React.useState<{ top: number; left: number } | null>(null)
  const bubble = React.useRef<HTMLDivElement>(null)
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
    setAnchor(trigger.getBoundingClientRect())
    setPos(null)
    setOpen(true)
  }, [trigger, disabled, hide])
  const hover = React.useCallback(() => {
    suppressed.current = false
    if (!canHover() || disabled) return
    clearTimeout(timer.current)
    if (activeTooltip || (lastClosed !== null && Date.now() - lastClosed < 300)) show()
    else timer.current = setTimeout(show, 600)
  }, [disabled, show])

  const focus = React.useCallback(() => { if (trigger?.matches(':focus-visible')) show() }, [trigger, show])
  const pointerDown = React.useCallback(() => { suppressed.current = true; hide() }, [hide])
  // Misura la bolla prima di disegnarla: se dal lato scelto esce dalla finestra passa al lato
  // opposto, e resta comunque dentro la finestra (4.2.3.1: gomma ed evidenziatore in cima).
  React.useLayoutEffect(() => {
    if (!open || !anchor || !bubble.current) return
    const { offsetWidth: w, offsetHeight: h } = bubble.current
    setPos(placeTooltip(anchor, { width: w, height: h }, side, { width: window.innerWidth, height: window.innerHeight }))
  }, [open, anchor, side, content])
  const visible = open && !disabled && anchor !== null
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
  return (
    <>
      {/* oxlint-disable-next-line react/refs -- Il render-prop passa i gestori al trigger; i ref si leggono solo negli eventi. */}
      {children(props)}
      {/* Sempre nel DOM per aria-describedby; visibile solo quando aperto. */}
      {createPortal(
        <div
          ref={bubble}
          id={id}
          role="tooltip"
          hidden={!visible}
          style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: 'hidden' }}
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

