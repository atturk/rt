/**
 * "Questa parte" del menu contestuale della lezione (linee guida §3): la subunità che contiene la
 * selezione, tutte quelle toccate se la selezione ne attraversa più di una; sul titolo di
 * un'unità (## 2 …) l'unità intera con le sue subunità (2.1, 2.2, …).
 *
 * Il documento è una sequenza di blocchi (i figli dell'<article>): ognuno appartiene alla
 * subunità e all'unità dell'ultima intestazione che lo precede.
 */
export type DocBlock = {
  /** Subunità del blocco (id del draft, per esempio "2.1"); null prima della prima o fra il titolo di un'unità e la sua prima subunità. */
  unit: string | null
  /** Unità madre (per esempio "2"); null nel titolo e nell'introduzione della lezione. */
  macro: string | null
  /** Il blocco è l'intestazione di un'unità (macro) o di una subunità (unit). */
  heading: 'macro' | 'unit' | null
}

/** Unità madre di una subunità: "2.1" → "2", "3" → "3". */
export function macroOf(unitId: string): string {
  const dot = unitId.lastIndexOf('.')
  return dot < 0 ? unitId : unitId.slice(0, dot)
}

/** Subunità di un'unità, nell'ordine del documento. */
export function unitsOfMacro(unitIds: readonly string[], macro: string): string[] {
  return unitIds.filter((id) => macroOf(id) === macro)
}

/** Numero all'inizio del titolo di un'unità ("2 Fasi del ciclo" → "2", "2. Fasi" → "2"). */
export function headingNumber(text: string): string | null {
  const match = text.trim().match(/^(\d+(?:\.\d+)*)\.?(?:\s|$)/)
  return match ? match[1] : null
}

/**
 * Subunità della parte fra i blocchi `from` e `to` (inclusi, in qualsiasi ordine): quelle dei
 * blocchi toccati. Il titolo di un'unità (o il testo prima della sua prima subunità) vale
 * l'unità intera solo se la parte non tocca nessuna delle sue subunità: una selezione che dalla
 * 1.2 scende nella 2.1 attraversa il titolo dell'unità 2 ma è 1.2 e 2.1. Nell'ordine del
 * documento, senza doppioni.
 */
export function partOfRange(blocks: readonly DocBlock[], from: number, to: number, unitIds: readonly string[]): string[] {
  const lo = Math.max(0, Math.min(from, to))
  const hi = Math.min(blocks.length - 1, Math.max(from, to))
  const picked = new Set<string>()
  const whole = new Set<string>()
  for (let i = lo; i <= hi; i++) {
    const block = blocks[i]
    if (block.unit) picked.add(block.unit)
    else if (block.macro) whole.add(block.macro)
  }
  const touched = new Set([...picked].map(macroOf))
  for (const macro of whole) if (!touched.has(macro)) unitsOfMacro(unitIds, macro).forEach((id) => picked.add(id))
  return unitIds.filter((id) => picked.has(id))
}

/** Blocchi dell'<article> del documento (DocumentView): intestazioni con data-unit-id per le subunità, numero nel testo per le unità. */
export function documentBlocks(article: Element, unitIds: readonly string[]): DocBlock[] {
  const known = new Set(unitIds)
  const macros = new Set(unitIds.map(macroOf))
  let unit: string | null = null
  let macro: string | null = null
  return Array.from(article.children).map((el) => {
    const id = (el as HTMLElement).dataset?.unitId
    if (id && known.has(id)) {
      unit = id
      macro = macroOf(id)
      return { unit, macro, heading: 'unit' as const }
    }
    if (/^H[1-3]$/.test(el.tagName)) {
      const number = el.tagName === 'H1' ? null : headingNumber(el.textContent ?? '')
      if (number && macros.has(number)) {
        unit = null
        macro = number
        return { unit, macro, heading: 'macro' as const }
      }
      if (el.tagName === 'H1') {
        unit = null
        macro = null
      }
    }
    return { unit, macro, heading: null }
  })
}

/** Blocchi del Markdown della lezione, uno per riga: `### 1.1 Titolo` apre una subunità, `## 1. Titolo` un'unità. */
export function markdownBlocks(lines: readonly string[], unitIds: readonly string[]): DocBlock[] {
  const known = new Set(unitIds)
  const macros = new Set(unitIds.map(macroOf))
  let unit: string | null = null
  let macro: string | null = null
  return lines.map((line) => {
    const sub = /^###\s+(\S+)/.exec(line)
    if (sub && known.has(sub[1])) {
      unit = sub[1]
      macro = macroOf(unit)
      return { unit, macro, heading: 'unit' as const }
    }
    const top = /^##\s+(.*)$/.exec(line)
    const number = top ? headingNumber(top[1]) : null
    if (number && macros.has(number)) {
      unit = null
      macro = number
      return { unit, macro, heading: 'macro' as const }
    }
    if (/^#\s/.test(line)) {
      unit = null
      macro = null
    }
    return { unit, macro, heading: null }
  })
}

/** Indice del blocco (figlio diretto dell'article) che contiene il nodo; -1 se è fuori. */
export function blockIndex(article: Element, node: Node | null): number {
  let el: Node | null = node
  while (el && el.parentNode !== article) el = el.parentNode
  return el ? Array.prototype.indexOf.call(article.children, el) : -1
}

/** Testo della parte per i messaggi: "1.1", "1.1 e 1.2", "1.1, 1.2 e 1.3". */
export function partLabel(units: string[]): string {
  if (units.length <= 1) return units[0] ?? ''
  return `${units.slice(0, -1).join(', ')} e ${units[units.length - 1]}`
}
