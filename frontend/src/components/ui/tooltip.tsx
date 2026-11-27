import * as React from 'react'
import { createPortal } from 'react-dom'

import { placeTooltip, type TooltipSide } from '@/lib/tooltipPlacement'
import { cn } from '@/lib/utils'

// Un solo suggerimento aperto; il gruppo resta caldo per 300 ms dopo la chiusura.
let activeTooltip: (() => void) | null = null
let pendingTooltip: (() => void) | null = null
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
  onClick?: () => void
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
  delay = 600,
  openOnClick = false,
  children,
}: {
  content: React.ReactNode
  side?: Side
  describe?: boolean
  disabled?: boolean
  delay?: number
  /** Il clic sul trigger apre e chiude il suggerimento (pulsanti «i» e «?»): serve anche al tocco. */
  openOnClick?: boolean
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
    if (pendingTooltip === hideTooltip) pendingTooltip = null
    if (activeTooltip === hideTooltip) {
      activeTooltip = null
      lastClosed = Date.now()
    }
    setOpen(false)
  }, [])
  React.useEffect(() => hide, [hide])

  const show = React.useCallback((force = false) => {
    clearTimeout(timer.current)
    timer.current = undefined
    if (pendingTooltip !== hide) pendingTooltip?.()
    pendingTooltip = null
    if (!trigger || disabled || (!force && (suppressed.current || !canHover()))) return
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
    // Un trigger annidato deve annullare anche l'apertura ancora in attesa del genitore.
    if (pendingTooltip !== hide) pendingTooltip?.()
    pendingTooltip = hide
    if (delay === 0 || activeTooltip || (lastClosed !== null && Date.now() - lastClosed < 300)) show()
    else timer.current = setTimeout(() => show(), delay)
  }, [disabled, delay, hide, show])

  const focus = React.useCallback(() => { if (trigger?.matches(':focus-visible')) show() }, [trigger, show])
  const pointerDown = React.useCallback(() => {
    if (openOnClick) return
    suppressed.current = true
    hide()
  }, [hide, openOnClick])
  // Fissato dal clic: resta aperto anche quando il mouse esce, finché non si clicca di nuovo o altrove.
  const pinned = React.useRef(false)
  const click = React.useCallback(() => {
    if (pinned.current) {
      pinned.current = false
      hide()
    } else {
      pinned.current = true
      show(true)
    }
  }, [hide, show])
  const leave = React.useCallback(() => { if (!pinned.current) hide() }, [hide])
  // Aperto col clic: si chiude toccando altrove o scorrendo la pagina.
  React.useEffect(() => {
    if (!openOnClick || !open) return
    const close = () => { pinned.current = false; hide() }
    const away = (e: Event) => { if (!trigger?.contains(e.target as Node)) close() }
    document.addEventListener('pointerdown', away, true)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('pointerdown', away, true)
      window.removeEventListener('scroll', close, true)
    }
  }, [openOnClick, open, trigger, hide])
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
    onMouseLeave: leave,
    onFocus: focus,
    onPointerDown: pointerDown,
    onBlur: leave,
    // Solo se richiesto: un onClick undefined sovrascriverebbe quello del trigger.
    ...(openOnClick ? { onClick: click } : {}),
    onKeyDown: (e) => {
      // Solo se il suggerimento si vede: altrimenti Esc va a chi lo aspetta (menu, dialoghi).
      if (e.key === 'Escape' && visible) {
        e.stopPropagation()
        pinned.current = false
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
            'pointer-events-none fixed z-[60] max-w-[min(18rem,calc(100vw-1rem))] rounded-md bg-foreground px-2 py-1 text-xs leading-snug text-background shadow-lg',
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

