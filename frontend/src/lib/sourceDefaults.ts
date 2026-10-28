import { FileImage, GitMerge, Image, Layers, Navigation, Type, type LucideIcon } from 'lucide-react'

import { textOnly, type Extraction, type SourceOptions } from '@/api/archive'
import { usePreference } from './preferences'

export type SourceKind = 'slide' | 'testo' | 'immagine'
export type SourceDefault = { estrai: Extraction; uso: 'contesto' | 'integra' }
export type SourceDefaults = Record<SourceKind, SourceDefault>

/** Slide e immagini: testo e immagini; testi (PDF verticali, Word, TXT, MD): solo testo. Sempre Contesto. */
export const SOURCE_DEFAULTS: SourceDefaults = {
  slide: { estrai: 'immagini', uso: 'contesto' },
  testo: { estrai: 'testo', uso: 'contesto' },
  immagine: { estrai: 'immagini', uso: 'contesto' },
}

export const isImageName = (name: string) => /\.(png|jpe?g|heic|webp|gif)$/i.test(name)
export const hasPages = (name: string) => /\.(pdf|pptx)$/i.test(name)

/** Che tipo di fonte è: per i PDF decide l'orientamento (estrai predefinito dal server). */
export function sourceKind(name: string, inspected?: Extraction | null): SourceKind {
  if (textOnly(name)) return 'testo'
  if (isImageName(name)) return 'immagine'
  if (/\.pdf$/i.test(name)) return inspected === 'testo' ? 'testo' : 'slide'
  return 'slide'
}

export function defaultOptions(name: string, defaults: SourceDefaults, inspected?: Extraction | null): SourceOptions {
  const chosen = defaults[sourceKind(name, inspected)]
  return { estrai: textOnly(name) ? 'testo' : chosen.estrai, uso: chosen.estrai === 'solo_immagini' ? 'contesto' : chosen.uso, pagine: null }
}

export function useSourceDefaults(): [SourceDefaults, (value: SourceDefaults) => void] {
  const [stored, set] = usePreference<Partial<SourceDefaults>>('sources.defaults', SOURCE_DEFAULTS)
  return [{ ...SOURCE_DEFAULTS, ...stored }, set]
}

export type Uso = NonNullable<SourceOptions['uso']>
export type Reasons<T extends string> = Partial<Record<T, string | null>>

export const EXTRACTIONS: [Extraction, LucideIcon, string][] = [
  ['testo', Type, 'Testo'],
  ['immagini', FileImage, 'Testo e immagini'],
  ['solo_immagini', Image, 'Solo immagini'],
]
export const USES: [Uso, LucideIcon, string][] = [
  ['guida', Navigation, 'Guida'],
  ['contesto', Layers, 'Contesto'],
  ['integra', GitMerge, 'Integra'],
]
/** "1-10" → [1, 10]; null = tutte. */
export function pageRange(value: string | number[] | null | undefined): [number, number] | null {
  if (value == null || value === '') return null
  const numbers = Array.isArray(value) ? value : value.split(/[^0-9]+/).filter(Boolean).map(Number)
  return numbers.length ? [Math.min(...numbers), Math.max(...numbers)] : null
}

/** Perché un pulsante delle fonti non è disponibile. */
export function sourceReasons({ name, options, hasAudio, isGuide }: { name: string; options: SourceOptions; hasAudio: boolean; isGuide: boolean }) {
  const onlyText = textOnly(name) ? 'Solo testo per Word, TXT e MD' : null
  const keepGuide = isGuide ? 'Serve una guida: scegline un’altra' : null
  return {
    extract: { immagini: onlyText, solo_immagini: onlyText || (isGuide ? 'La guida ha bisogno del testo' : null) } as Reasons<Extraction>,
    use: { guida: hasAudio ? 'Con una registrazione la guida è l’audio' : null, contesto: keepGuide, integra: keepGuide } as Reasons<Uso>,
    off: options.estrai === 'solo_immagini' ? 'Solo immagini: nessun testo da usare' : null,
  }
}
