import { usePreference } from './preferences'

/** Preferenze della lettura veloce (pref `study.rsvp`, anche in Impostazioni › Aspetto e lettura). */
export type RsvpPreference = {
  wpm: number; orp: 'prima' | 'bilanciata' | 'dopo'; pauseMs: number; comma: boolean
  step: number; size: number; sound: boolean; pitch: number; dyslexic: boolean
  irlen: null | 'pesca' | 'menta' | 'pergamena'; noise: null | 'bianco' | 'rosa' | 'marrone'; noiseVolume: number
}
export const RSVP_DEFAULT: RsvpPreference = { wpm: 300, orp: 'bilanciata', pauseMs: 400, comma: false,
  step: 5, size: 60, sound: true, pitch: 1, dyslexic: false, irlen: null, noise: null, noiseVolume: 0.25 }

/** Evidenziatore dello Studio (pref `study.highlighter`): ultimo colore usato e frecce ← →. */
export type HighlighterPreference = { color: number; arrows: boolean }
export const HIGHLIGHTER_DEFAULT: HighlighterPreference = { color: 0, arrows: true }

/** Valori salvati da una versione precedente possono non avere tutti i campi. */
function usePartial<T extends object>(name: string, fallback: T): [T, (value: T) => void] {
  const [value, set] = usePreference<Partial<T>>(name, fallback)
  return [{ ...fallback, ...value }, set]
}

export const useRsvpPrefs = () => usePartial('study.rsvp', RSVP_DEFAULT)
export const useHighlighterPrefs = () => usePartial('study.highlighter', HIGHLIGHTER_DEFAULT)
