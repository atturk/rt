import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'

type AudioState = {
  audioRef: RefObject<HTMLAudioElement | null>
  currentTime: number
  setCurrentTime: (t: number) => void
  /** Sposta l'audio e avvia la riproduzione (anche prima che i metadati siano caricati). */
  seek: (seconds: number, play?: boolean) => void
}

const AudioContext = createContext<AudioState | null>(null)

/** Stato del player condiviso da documento e player: è stato dell'interfaccia, non di dominio. */
export function AudioProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const seek = useCallback((seconds: number, play = true) => {
    const audio = audioRef.current
    if (!audio || !Number.isFinite(seconds)) return
    const apply = () => {
      audio.currentTime = Math.max(0, Math.min(seconds, Number.isFinite(audio.duration) ? audio.duration : seconds))
      setCurrentTime(audio.currentTime)
      if (play) audio.play().catch(() => undefined)
    }
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) apply()
    else audio.addEventListener('loadedmetadata', apply, { once: true })
  }, [])
  const value = useMemo(() => ({ audioRef, currentTime, setCurrentTime, seek }), [currentTime, seek])
  return <AudioContext.Provider value={value}>{children}</AudioContext.Provider>
}

// oxlint-disable-next-line react/only-export-components
export function useLessonAudio(): AudioState {
  const ctx = useContext(AudioContext)
  if (!ctx) throw new Error('useLessonAudio fuori da AudioProvider')
  return ctx
}

