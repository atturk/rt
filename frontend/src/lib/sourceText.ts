/** Testo dello Studio: ogni formula vale il suo sorgente, senza annotazioni MathML o copie visive. */
export type SourcePart = { node: Text | Element; text: string; start: number; end: number }
const OMIT = '.rt-image-strip-slot, .rt-math-src, script, style'

export function sourceParts(root: Node): SourcePart[] {
  const parts: SourcePart[] = []
  let offset = 0
  const visit = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element
      if (el.matches(OMIT)) return
      if (el.matches('math')) {
        const text = el.getAttribute('data-rt-source') ?? ''
        parts.push({ node: el, text, start: offset, end: offset + text.length })
        offset += text.length
        return
      }
    }
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent ?? ''
      parts.push({ node: node as Text, text, start: offset, end: offset + text.length })
      offset += text.length
    } else node.childNodes.forEach(visit)
  }
  visit(root)
  return parts
}

export function sourceTextOf(root: Node): string {
  return sourceParts(root).map(p => p.text).join('')
}

function partRange(part: SourcePart): Range {
  const range = part.node.ownerDocument!.createRange()
  if (part.node.nodeType === Node.TEXT_NODE) range.selectNodeContents(part.node)
  else {
    range.selectNode(part.node)
    // Anche selezionare il LaTeX visibile equivale a toccare la formula accanto.
    const next = part.node.nextSibling
    if (next?.nodeType === Node.ELEMENT_NODE && (next as Element).matches('.rt-math-src')) range.setEndAfter(next)
  }
  return range
}

/** I confini possono essere testo, elementi o token MathML; le formule sono indivisibili. */
export function sourceOffsets(root: Node, range: Range): { text: string; start: number; end: number } {
  const parts = sourceParts(root)
  const result = { text: parts.map(p => p.text).join(''), start: 0, end: 0 }
  if (range.collapsed) return result
  const first = range.cloneRange(), last = range.cloneRange()
  first.collapse(true)
  last.collapse(false)
  let found = false
  for (const part of parts) {
    if (!part.text) continue
    const bounds = partRange(part), left = bounds.cloneRange(), right = bounds.cloneRange()
    left.collapse(true)
    right.collapse(false)
    if (last.compareBoundaryPoints(Range.START_TO_START, left) <= 0 || first.compareBoundaryPoints(Range.START_TO_START, right) >= 0) continue
    const start = part.start + (range.startContainer === part.node && part.node.nodeType === Node.TEXT_NODE ? range.startOffset : 0)
    const end = part.node === range.endContainer && part.node.nodeType === Node.TEXT_NODE ? part.start + range.endOffset : part.end
    if (!found) result.start = start
    result.end = end
    found = true
  }
  return result
}

/** Riporta un intervallo sorgente sul DOM senza entrare nel MathML. */
export function sourceRange(root: Node, start: number, end: number): Range | null {
  const parts = sourceParts(root).filter(p => p.end > start && p.start < end)
  if (!parts.length) return null
  const first = parts[0], last = parts.at(-1)!
  const range = partRange(first)
  if (first.node.nodeType === Node.TEXT_NODE) range.setStart(first.node, Math.max(0, start - first.start))
  if (last.node.nodeType === Node.TEXT_NODE) range.setEnd(last.node, Math.min(last.text.length, end - last.start))
  else range.setEndAfter(last.node.nextSibling?.nodeType === Node.ELEMENT_NODE && (last.node.nextSibling as Element).matches('.rt-math-src') ? last.node.nextSibling : last.node)
  return range
}
