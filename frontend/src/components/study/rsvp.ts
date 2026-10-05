/**
 * Logica della lettura veloce (4.2.2, task V1), senza DOM tranne `readUnitWords`.
 * Una parola è *normale* o *fine frase*: con "Virgola come pausa piena" anche , ; : chiudono.
 */
import type { RsvpPreference } from '@/lib/studyPrefs'

export type Word = { text: string; para: number }
/** Pezzo del Contesto: una parola letta (index) o un elemento saltato (formula, immagine, tabella). */
export type ContextPiece = { text: string; index: number | null }

const SENTENCE_END = /[.!?…]["'»”’)\]]*$/
const SOFT_END = /[,;:]["'»”’)\]]*$/
const ORP_SHARE = { prima: 0.25, bilanciata: 0.35, dopo: 0.5 } as const
export const MIN_WPM = 100
export const MAX_WPM = 900

/** Divide un testo in parole (spazi, a capo), senza parole vuote. */
export function splitWords(text: string): string[] {
  return text.split(/\s+/).filter(Boolean)
}

export function endsSentence(word: string): boolean {
  return SENTENCE_END.test(word)
}

/** Seconda forma di parola: fine frase, o virgola/punto e virgola/due punti con l'opzione. */
export function isFullStop(word: string, comma: boolean): boolean {
  return endsSentence(word) || (comma && SOFT_END.test(word))
}

/** Lettere e cifre della parola, senza punteggiatura. */
function letters(word: string): number {
  return word.replace(/[^\p{L}\p{N}]/gu, '').length
}

/** Indice della lettera di fuoco: 25/35/50 % delle lettere, punteggiatura iniziale esclusa. */
export function focusIndex(word: string, orp: RsvpPreference['orp']): number {
  const lead = word.length - word.replace(/^[^\p{L}\p{N}]+/u, '').length
  const core = word.slice(lead)
  const count = core.replace(/[^\p{L}\p{N}].*$/su, '').length || core.length
  return Math.min(word.length - 1, lead + Math.max(0, Math.round((count - 1) * ORP_SHARE[orp])))
}

/** Durata di una parola in ms. `ramp` (5…1) rallenta le prime parole dopo play. */
export function wordDelay(word: string, prefs: Pick<RsvpPreference, 'wpm' | 'pauseMs' | 'comma'>, ramp = 0): number {
  let ms = 60000 / prefs.wpm
  const count = letters(word)
  if (count > 8) ms *= 1 + (count - 8) * 0.06
  if (isFullStop(word, prefs.comma)) ms += prefs.pauseMs
  if (ramp > 0) ms *= 1 + ramp * 0.12
  return ms
}

/** Inizio della frase precedente; se si è già all'inizio di una frase, quella prima ancora. */
export function previousSentence(words: Word[], i: number): number {
  const startOf = (k: number) => {
    while (k > 0 && !endsSentence(words[k - 1].text)) k--
    return k
  }
  const here = startOf(i)
  return here < i ? here : Math.max(0, startOf(Math.max(0, here - 1)))
}

/** Inizio della frase successiva (o l'ultima parola). */
export function nextSentence(words: Word[], i: number): number {
  let k = i
  while (k < words.length - 1 && !endsSentence(words[k].text)) k++
  return Math.min(k + 1, words.length - 1)
}

/** Testo intorno, solo in pausa: la frase fino alla parola sopra, il resto sotto (max 12 per lato). */
export function surrounding(words: Word[], i: number, max = 12): { before: string; after: string } {
  const before: string[] = []
  for (let k = i - 1; k >= 0 && !endsSentence(words[k].text) && before.length < max; k--) before.unshift(words[k].text)
  const after: string[] = []
  if (words[i] && !endsSentence(words[i].text)) {
    for (let k = i + 1; k < words.length && after.length < max; k++) {
      after.push(words[k].text)
      if (endsSentence(words[k].text)) break
    }
  }
  return { before: before.join(' '), after: after.join(' ') }
}

/** Secondi che mancano alla fine, alla velocità attuale. */
export function remainingSeconds(total: number, i: number, wpm: number): number {
  return Math.max(0, Math.round(((total - i - 1) / wpm) * 60))
}

export function formatRemaining(seconds: number): string {
  const m = Math.floor(seconds / 60)
  return m ? `${m} min ${seconds % 60} s` : `${seconds} s`
}

const SKIP = '.katex, .katex-display, math, img, picture, figure, table, svg, video, audio, pre'
const BLOCK = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, dd, dt, td, th, figcaption, div'

function skipLabel(el: Element): string {
  if (el.matches('.katex, .katex-display, math')) return '[formula]'
  if (el.matches('table')) return '[tabella]'
  if (el.matches('pre')) return '[codice]'
  return '[immagine]'
}

/**
 * Parole del testo dell'unità (l'HTML già sanificato di UnitText): formule, immagini e tabelle
 * si saltano e nel Contesto restano come segnaposto. `para` raggruppa le parole per blocco.
 */
export function readUnitWords(root: Element): { words: Word[]; paragraphs: ContextPiece[][] } {
  const words: Word[] = []
  const paragraphs: ContextPiece[][] = []
  const blocks = new Map<Element | null, number>()
  const paraOf = (node: Node) => {
    const block = (node.parentElement?.closest(BLOCK) ?? null) as Element | null
    const key = block && root.contains(block) && block !== root ? block : null
    let index = blocks.get(key)
    if (index === undefined) {
      index = paragraphs.length
      blocks.set(key, index)
      paragraphs.push([])
    }
    return index
  }
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => node.nodeType === Node.ELEMENT_NODE && (node as Element).matches(SKIP)
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  })
  // Gli elementi saltati non si visitano: restano nel Contesto come segnaposto, al loro posto.
  const marks: { node: Node; label: string }[] = []
  root.querySelectorAll(SKIP).forEach((el) => { if (!el.parentElement?.closest(SKIP)) marks.push({ node: el, label: skipLabel(el) }) })
  let next = 0
  const flushMarksBefore = (node: Node) => {
    while (next < marks.length && (marks[next].node.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)) {
      paragraphs[paraOf(marks[next].node)].push({ text: marks[next].label, index: null })
      next++
    }
  }
  let glue = false // il nodo di testo precedente finiva a metà parola (es. <b>pa</b>rola)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType !== Node.TEXT_NODE) continue
    const before = next
    flushMarksBefore(node)
    const text = node.textContent ?? ''
    const para = paraOf(node)
    const parts = splitWords(text)
    const last = words[words.length - 1]
    if (glue && before === next && last?.para === para && parts.length && !/^\s/.test(text)) {
      last.text += parts.shift()
      const piece = paragraphs[para].findLast((p) => p.index === words.length - 1)
      if (piece) piece.text = last.text
    }
    for (const word of parts) {
      paragraphs[para].push({ text: word, index: words.length })
      words.push({ text: word, para })
    }
    if (text) glue = !!text.trim() && !/\s$/.test(text)
  }
  while (next < marks.length) {
    paragraphs[paraOf(marks[next].node)].push({ text: marks[next].label, index: null })
    next++
  }
  return { words, paragraphs }
}
