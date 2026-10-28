import { useCallback, useSyncExternalStore } from 'react'

import { usePreference } from './preferences'

/** Font del testo dello Studio: [valore, etichetta, stack CSS]. */
export const STUDY_FONTS = [
  ['sistema', 'Sistema', 'var(--font-sans)'],
  ['seravek', 'Seravek', "Seravek, 'Gill Sans Nova', 'Avenir Next', var(--font-sans)"],
  ['avenir', 'Avenir Next', "'Avenir Next', Avenir, var(--font-sans)"],
  ['georgia', 'Georgia', "Georgia, 'Iowan Old Style', serif"],
  ['dislessia', 'OpenDyslexic', "'OpenDyslexic', var(--font-sans)"],
] as const

export type StudyFont = typeof STUDY_FONTS[number][0]
export const STUDY_FONT_DEFAULT: StudyFont = 'sistema'

function isStudyFont(value: unknown): value is StudyFont {
  return STUDY_FONTS.some(([v]) => v === value)
}

export function studyFontStack(value: string): string {
  return (STUDY_FONTS.find(([v]) => v === value) ?? STUDY_FONTS[0])[2]
}

/** Font scelto per il testo dello Studio (pref condivisa `study.text-font`). */
export function useStudyFont(): [StudyFont, (value: StudyFont) => void] {
  const [value, set] = usePreference<string>('study.text-font', STUDY_FONT_DEFAULT)
  return [isStudyFont(value) ? value : STUDY_FONT_DEFAULT, set]
}

// Font di sistema da misurare: gli altri (stack generico, OpenDyslexic servito dall'app) ci sono sempre.
const MEASURED: Partial<Record<StudyFont, string>> = { seravek: 'Seravek', avenir: 'Avenir Next', georgia: 'Georgia' }

/** Confronta su un canvas la larghezza di un testo col font e col solo fallback; senza canvas risponde true. */
export function fontAvailable(name: string): boolean {
  try {
    const ctx = document.createElement('canvas').getContext('2d')
    if (!ctx) return true
    const sample = 'mmmmmmmmmmlliWWQ@#0123456789'
    return ['monospace', 'serif', 'sans-serif'].some(base => {
      ctx.font = `72px ${base}`
      const fallback = ctx.measureText(sample).width
      ctx.font = `72px "${name}", ${base}`
      return ctx.measureText(sample).width !== fallback
    })
  } catch { return true }
}

export function studyFontAvailable(value: StudyFont): boolean {
  const name = MEASURED[value]
  return name === undefined || fontAvailable(name)
}

// Dimensione del testo: per dispositivo, la cambiano lo Studio (+ e −) e le impostazioni.
export const STUDY_TEXT_SCALE_KEY = 'rt-device:study-text-scale'
export const STUDY_TEXT_SCALE_MIN = 0.8
export const STUDY_TEXT_SCALE_MAX = 2.0

export function clampStudyTextScale(v: number): number {
  if (!Number.isFinite(v)) return 1
  return Math.min(STUDY_TEXT_SCALE_MAX, Math.max(STUDY_TEXT_SCALE_MIN, Math.round(v * 10) / 10))
}

export function getSavedStudyTextScale(): number {
  try {
    const raw = localStorage.getItem(STUDY_TEXT_SCALE_KEY)
    if (raw) {
      const val = parseFloat(raw)
      if (Number.isFinite(val) && val >= STUDY_TEXT_SCALE_MIN && val <= STUDY_TEXT_SCALE_MAX) return Math.round(val * 10) / 10
    }
  } catch { return 1 }
  return 1
}

const listeners = new Set<() => void>()

export function saveStudyTextScale(v: number): void {
  try {
    localStorage.setItem(STUDY_TEXT_SCALE_KEY, clampStudyTextScale(v).toFixed(1))
  } catch { /* Continua se localStorage non è disponibile. */ }
  listeners.forEach(l => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  const onStorage = (e: StorageEvent) => { if (e.key === null || e.key === STUDY_TEXT_SCALE_KEY) listener() }
  window.addEventListener('storage', onStorage)
  return () => { listeners.delete(listener); window.removeEventListener('storage', onStorage) }
}

/** Scala del testo dello Studio, condivisa fra Studio e impostazioni (e fra le finestre). */
export function useStudyTextScale(): [number, (v: number) => void] {
  const scale = useSyncExternalStore(subscribe, getSavedStudyTextScale, () => 1)
  const set = useCallback((v: number) => saveStudyTextScale(v), [])
  return [scale, set]
}
