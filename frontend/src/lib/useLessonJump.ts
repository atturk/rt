import { useEffect, useRef, useState } from 'react'

export type JumpSide = 'left' | 'right'
/** Ogni pressione e l'uscita del mouse fanno ripartire i cinque secondi. */
export function useLessonJump() {
  const [jump, setJump] = useState<{ side: JumpSide; sequence: number } | null>(null)
  const [paused, setPaused] = useState(false)
  const sequence = useRef(0)
  const show = (side: JumpSide) => { setJump({ side, sequence: ++sequence.current }); setPaused(false) }
  const close = () => { setJump(null); setPaused(false) }
  const pause = () => setPaused(true)
  const resume = () => { setPaused(false); setJump(current => current ? { ...current, sequence: ++sequence.current } : null) }
  useEffect(() => {
    if (!jump || paused) return
    const timer = setTimeout(() => setJump(null), 5000)
    return () => clearTimeout(timer)
  }, [jump, paused])
  return { jump, paused, show, close, pause, resume }
}

