import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/** Soglia in pixel entro cui l'utente è considerato "in fondo" alla lista. */
export const TAIL_THRESHOLD = 24

export function isNearBottom(el: Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>, threshold = TAIL_THRESHOLD): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
}

/**
 * Scorrimento automatico "intelligente" di un log: segue la coda finché l'utente è in fondo,
 * si ferma appena scorre verso l'alto e riprende quando torna in fondo (anche con
 * jumpToLatest, il pulsante "Vai agli ultimi"). `count` è il numero di righe: quando cambia e
 * si sta seguendo la coda, il log scorre all'ultima. onScroll va sull'elemento scorrevole.
 */
export function useFollowTail<T extends HTMLElement>(count: number) {
  const ref = useRef<T>(null)
  const [following, setFollowing] = useState(true)
  const followingRef = useRef(true)

  const setFollow = useCallback((value: boolean) => {
    followingRef.current = value
    setFollowing(value)
  }, [])

  const onScroll = useCallback(() => {
    const el = ref.current
    if (!el) return
    const near = isNearBottom(el)
    if (near !== followingRef.current) setFollow(near)
  }, [setFollow])

  useLayoutEffect(() => {
    const el = ref.current
    if (el && followingRef.current) el.scrollTop = el.scrollHeight
  }, [count])

  const jumpToLatest = useCallback(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
    setFollow(true)
  }, [setFollow])

  return { ref, onScroll, following, jumpToLatest }
}
