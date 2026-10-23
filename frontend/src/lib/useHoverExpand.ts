import { useCallback, useEffect, useRef, useState } from 'react'

export interface UseHoverExpandOptions<T extends HTMLElement = HTMLElement> {
  /** Ritardo di chiusura in ms dopo l'uscita del puntatore (default: 3000 ms). */
  delayMs?: number
  /** Stato iniziale di apertura (default: false). */
  initialOpen?: boolean
  /** Callback chiamata quando lo stato di apertura cambia. */
  onOpenChange?: (open: boolean) => void
  /** Ref esterno opzionale; se non passato, l'hook crea e restituisce il proprio. */
  ref?: React.RefObject<T | null>
}

export interface UseHoverExpandResult<T extends HTMLElement = HTMLElement> {
  open: boolean
  setOpen: React.Dispatch<React.SetStateAction<boolean>>
  closeImmediately: () => void
  ref: React.RefObject<T | null>
}

/**
 * Gestisce l'apertura e chiusura ritardata di gruppi espandibili:
 * - si apre al passaggio del puntatore (o al focus)
 * - uscendo dal gruppo, attende 3 s prima di chiudersi
 * - rientrando prima dei 3 s, resta aperto
 * - clic/tocco fuori o Esc lo chiudono subito
 * - il focus da tastiera dentro il gruppo lo tiene aperto finché il focus non esce
 */
export function useHoverExpand<T extends HTMLElement = HTMLElement>(
  options: UseHoverExpandOptions<T> = {},
): UseHoverExpandResult<T> {
  const { delayMs = 3000, initialOpen = false, onOpenChange } = options
  const [open, setOpenState] = useState(initialOpen)
  const localRef = useRef<T | null>(null)
  const ref = options.ref ?? localRef
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isPointerInside = useRef(false)

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const setOpen = useCallback(
    (value: boolean | ((prev: boolean) => boolean)) => {
      setOpenState((prev) => {
        const next = typeof value === 'function' ? value(prev) : value
        if (!next) {
          clearTimer()
        }
        if (next !== prev) {
          onOpenChange?.(next)
        }
        return next
      })
    },
    [clearTimer, onOpenChange],
  )

  const closeImmediately = useCallback(() => {
    clearTimer()
    setOpen(false)
  }, [clearTimer, setOpen])

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const handlePointerEnter = () => {
      isPointerInside.current = true
      clearTimer()
      setOpen(true)
    }

    const handlePointerLeave = () => {
      isPointerInside.current = false
      if (timerRef.current) return
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        if (isPointerInside.current) return
        if (el.contains(document.activeElement)) return
        setOpen(false)
      }, delayMs)
    }

    const handleFocusIn = () => {
      clearTimer()
      setOpen(true)
    }

    const handleFocusOut = (e: FocusEvent) => {
      const nextTarget = e.relatedTarget as Node | null
      if (nextTarget && el.contains(nextTarget)) return
      if (!isPointerInside.current) {
        closeImmediately()
      }
    }

    el.addEventListener('pointerenter', handlePointerEnter)
    el.addEventListener('pointerleave', handlePointerLeave)
    el.addEventListener('mouseenter', handlePointerEnter)
    el.addEventListener('mouseleave', handlePointerLeave)
    el.addEventListener('focusin', handleFocusIn)
    el.addEventListener('focusout', handleFocusOut)

    return () => {
      el.removeEventListener('pointerenter', handlePointerEnter)
      el.removeEventListener('pointerleave', handlePointerLeave)
      el.removeEventListener('mouseenter', handlePointerEnter)
      el.removeEventListener('mouseleave', handlePointerLeave)
      el.removeEventListener('focusin', handleFocusIn)
      el.removeEventListener('focusout', handleFocusOut)
    }
  }, [clearTimer, closeImmediately, delayMs, ref, setOpen])

  useEffect(() => {
    if (!open) return

    const handleOutside = (e: Event) => {
      const target = e.target as Node | null
      if (!target) return
      if (ref.current && !ref.current.contains(target)) {
        closeImmediately()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeImmediately()
      }
    }

    document.addEventListener('pointerdown', handleOutside)
    document.addEventListener('mousedown', handleOutside)
    document.addEventListener('touchstart', handleOutside)
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('pointerdown', handleOutside)
      document.removeEventListener('mousedown', handleOutside)
      document.removeEventListener('touchstart', handleOutside)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeImmediately, open, ref])

  useEffect(() => {
    return () => {
      clearTimer()
    }
  }, [clearTimer])

  return { open, setOpen, closeImmediately, ref }
}
