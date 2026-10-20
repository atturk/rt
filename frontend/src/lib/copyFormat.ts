import { useEffect, useRef } from 'react'

import { delimiters } from './math'
import { usePreference } from './preferences'

/** Cosa tiene la copia del testo (pref `copy.format`, Impostazioni › Copia): per Anki e simili. */
export type CopyFormat = { bold: boolean; italic: boolean; highlights: boolean; color: boolean }
export const COPY_FORMAT_DEFAULT: CopyFormat = { bold: true, italic: true, highlights: true, color: false }

export function useCopyFormat(): [CopyFormat, (value: CopyFormat) => void] {
  const [value, set] = usePreference<Partial<CopyFormat>>('copy.format', COPY_FORMAT_DEFAULT)
  return [{ ...COPY_FORMAT_DEFAULT, ...value }, set]
}

// Colori dell'evidenziatore del tema chiaro: chi incolla (Anki) ha quasi sempre lo sfondo chiaro.
const HIGHLIGHT_BACKGROUNDS = ['#fde68a', '#bbf7d0', '#bae6fd', '#fbcfe8', '#fed7aa']
const KEEP = new Set(['P', 'BR', 'UL', 'OL', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'PRE', 'CODE',
  'SUB', 'SUP', 'U', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'A', 'IMG', 'HR'])
const BOLD = new Set(['B', 'STRONG'])
const ITALIC = new Set(['I', 'EM'])
const SKIP = 'script, style, button, [aria-hidden="true"], .rt-math-src'

function highlight(el: Element): string | null {
  if (!el.classList.contains('rt-hl')) return null
  const color = Array.from(el.classList).find(c => /^rt-hl-\d$/.test(c))
  return HIGHLIGHT_BACKGROUNDS[color ? Number(color.slice(6)) : 0] ?? HIGHLIGHT_BACKGROUNDS[0]
}

function escape(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function attr(value: string): string {
  return escape(value).replace(/"/g, '&quot;')
}

/** La formula come la vuole Anki (MathJax): \( … \) o \[ … \]. */
function mathSource(el: Element): string {
  const original = el.getAttribute('data-rt-source')
  if (!original) return escape(el.textContent ?? '')
  const [source, display] = delimiters(original)
  return escape(display ? `\\[${source.trim()}\\]` : `\\(${source.trim()}\\)`)
}

/**
 * HTML pulito della selezione: struttura (paragrafi, elenchi, titoli, tabelle) sempre, poi solo
 * gli stili scelti. Niente classi né stili della pagina, così il tema scuro non arriva nella nota.
 */
export function selectionHtml(range: Range, format: CopyFormat): string {
  const base = getComputedStyle(document.body).color

  const text = (node: Text): string => {
    let value = node.data
    if (node === range.endContainer) value = value.slice(0, range.endOffset)
    if (node === range.startContainer) value = value.slice(range.startOffset)
    if (!value) return ''
    const out = escape(value)
    const parent = node.parentElement
    if (!format.color || !parent) return out
    const color = getComputedStyle(parent).color
    return color && color !== base ? `<span style="color: ${attr(color)}">${out}</span>` : out
  }

  const element = (el: Element): string => {
    if (el.matches(SKIP)) return ''
    if (el.matches('math, .rt-math')) return mathSource(el)
    const inner = children(el)
    const tag = el.tagName
    const hl = highlight(el)
    if (hl) return format.highlights && inner ? `<span style="background-color: ${hl}">${inner}</span>` : inner
    if (BOLD.has(tag)) return format.bold && inner ? `<b>${inner}</b>` : inner
    if (ITALIC.has(tag)) return format.italic && inner ? `<i>${inner}</i>` : inner
    if (tag === 'DIV' && inner && getComputedStyle(el).display === 'block' && !el.querySelector('p, li, h1, h2, h3, h4, h5, h6, div, table')) return `<p>${inner}</p>`
    if (!KEEP.has(tag)) return inner
    if (tag === 'BR' || tag === 'HR') return `<${tag.toLowerCase()}>`
    if (tag === 'IMG') {
      const src = (el as HTMLImageElement).src
      return src ? `<img src="${attr(src)}" alt="${attr(el.getAttribute('alt') ?? '')}">` : ''
    }
    const name = tag.toLowerCase()
    const href = tag === 'A' ? (el as HTMLAnchorElement).href : ''
    const span = ['colspan', 'rowspan'].map(a => el.getAttribute(a) ? ` ${a}="${attr(el.getAttribute(a)!)}"` : '').join('')
    return `<${name}${href ? ` href="${attr(href)}"` : ''}${span}>${inner}</${name}>`
  }

  const children = (el: Node): string => {
    let out = ''
    for (const child of Array.from(el.childNodes)) {
      if (!range.intersectsNode(child)) continue
      if (child.nodeType === Node.TEXT_NODE) out += text(child as Text)
      else if (child.nodeType === Node.ELEMENT_NODE) out += element(child as Element)
    }
    return out
  }

  const common = range.commonAncestorContainer
  if (common.nodeType === Node.TEXT_NODE) {
    const parent = common.parentElement
    // Selezione dentro una sola parola in grassetto: si tiene lo stile del contenitore.
    let out = text(common as Text)
    for (let el = parent; el && out && !el.matches('p, li, h1, h2, h3, h4, h5, h6, td, th, body, [data-copy-root]'); el = el.parentElement) {
      if (el.matches('math, .rt-math')) return mathSource(el)
      if (BOLD.has(el.tagName) && format.bold) out = `<b>${out}</b>`
      else if (ITALIC.has(el.tagName) && format.italic) out = `<i>${out}</i>`
      else if (el.classList.contains('rt-hl') && format.highlights) out = `<span style="background-color: ${highlight(el)}">${out}</span>`
    }
    return out
  }
  return (common as Element).matches?.('math, .rt-math') ? mathSource(common as Element) : children(common)
}

/** Dove la copia resta quella del browser: campi di testo e editor. */
function editable(node: Node | null): boolean {
  const el = node instanceof Element ? node : node?.parentElement
  return !!el?.closest('input, textarea, [contenteditable=""], [contenteditable="true"], .cm-editor')
}

/**
 * Copia in tutta l'app con la formattazione scelta. Se un componente ha già scritto il testo
 * semplice (lo Studio con le formule), si aggiunge solo l'HTML.
 */
export function useCopyFormatter(): void {
  const [format] = useCopyFormat()
  const current = useRef(format)
  useEffect(() => { current.current = format }, [format])
  useEffect(() => {
    const onCopy = (event: ClipboardEvent) => {
      const sel = window.getSelection()
      if (!event.clipboardData || !sel?.rangeCount || sel.isCollapsed) return
      const range = sel.getRangeAt(0)
      if (editable(range.commonAncestorContainer) || editable(document.activeElement)) return
      const html = selectionHtml(range, current.current)
      if (!html.trim()) return
      if (!event.defaultPrevented) event.clipboardData.setData('text/plain', sel.toString())
      event.clipboardData.setData('text/html', html)
      event.preventDefault()
    }
    document.addEventListener('copy', onCopy)
    return () => document.removeEventListener('copy', onCopy)
  }, [])
}
