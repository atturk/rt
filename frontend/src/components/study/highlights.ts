import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import Highlighter from 'web-highlighter'

import { sourceOffsets, sourceParts, sourceRange } from '@/lib/sourceText'
import { highlightsApi } from '@/api/highlights'
import { mountDomTooltip } from '@/components/ui/dom-tooltip'

export type HighlightMode = 'evidenzia' | 'gomma' | 'verifica' | 'chiedi' | null
export const HIGHLIGHT_COLORS = ['giallo', 'verde', 'azzurro', 'rosa', 'arancio'] as const

type Stored = { startMeta: Parameters<Highlighter['fromStore']>[0]; endMeta: Parameters<Highlighter['fromStore']>[1]; text: string; id: string; sourceStart?: number; sourceEnd?: number }

/**
 * Evidenziatore dell'unità (4.2.2, H1) sul testo di UnitText: con "evidenzia" una selezione si
 * colora subito e si salva su RT; con "gomma" un clic toglie l'evidenziazione. All'apertura le
 * evidenziazioni salvate si ridisegnano; quelle il cui testo non si ritrova più si saltano.
 */
export function useStudyHighlighter({ root, lessonId, unitId, mode, color }: {
  root: HTMLElement | null
  lessonId: number
  unitId: string
  mode: HighlightMode
  color: number
}) {
  const highlighter = useRef<Highlighter | null>(null)
  const clearMath = useRef<() => void>(() => {})
  const saved = useRef(new Map<string, number>())
  const modeRef = useRef(mode)
  const colorRef = useRef(color)
  useLayoutEffect(() => {
    modeRef.current = mode
    colorRef.current = color
  }, [mode, color])

  useEffect(() => {
    if (!root) return
    // La libreria confronta i tag in maiuscolo; nel namespace MathML tagName resta minuscolo.
    const h = new Highlighter({ $root: root, wrapTag: 'span', exceptSelectors: ['math', '.rt-math', '.rt-math-src', '.rt-image-strip-slot', 'img', 'table'], style: { className: 'rt-hl' } })
    const ids = new Map<string, number>()
    highlighter.current = h
    saved.current = ids
    let alive = true
    let tripleClick = false
    let selected: ReturnType<typeof sourceOffsets> | null = null
    const mathMarks = new Map<Element, Map<string, number>>()
    const paintMath = (id: string, color: number, start: number, end: number) => {
      for (const part of sourceParts(root)) {
        if (part.node.nodeType !== Node.ELEMENT_NODE || part.start >= end || part.end <= start) continue
        const math = part.node as Element
        const marks = mathMarks.get(math) ?? new Map<string, number>()
        marks.set(id, color)
        mathMarks.set(math, marks)
      }
      refreshMath()
    }
    const refreshMath = () => {
      for (const [math, marks] of mathMarks) {
        math.classList.remove('rt-hl-math', ...HIGHLIGHT_COLORS.map((_, i) => `rt-hl-${i}`))
        const color = Array.from(marks.values()).at(-1)
        if (color !== undefined) math.classList.add('rt-hl-math', `rt-hl-${color}`)
      }
    }
    clearMath.current = () => { for (const marks of mathMarks.values()) marks.clear(); refreshMath() }
    const forgetMath = (id: string) => {
      for (const marks of mathMarks.values()) marks.delete(id)
      refreshMath()
    }
    const mathId = (target: Element) => {
      const math = target.closest('math') ?? (target.closest('.rt-math-src')?.previousElementSibling)
      return math ? Array.from(mathMarks.get(math)?.keys() ?? []).at(-1) : undefined
    }
    const persist = (body: Stored, chosen: number) => {
      highlightsApi.add(lessonId, { unit_id: unitId, color: chosen, source: body })
        .then(row => {
          if (alive && (h.getDoms(body.id).length || Array.from(mathMarks.values()).some(m => m.has(body.id)))) ids.set(body.id, row.id)
          else if (alive) void highlightsApi.remove(lessonId, row.id).catch(() => {})
        })
        .catch(() => { if (alive) { h.remove(body.id); forgetMath(body.id) } })
    }
    h.on(Highlighter.event.REMOVE, ({ ids: removed }) => removed.forEach(forgetMath))
    const remove = (id: string) => {
      h.remove(id)
      forgetMath(id)
      const row = ids.get(id)
      ids.delete(id)
      if (row !== undefined) void highlightsApi.remove(lessonId, row).catch(() => {})
    }
    const onMouseDown = (event: MouseEvent) => {
      tripleClick = event.detail >= 3
      if (tripleClick && modeRef.current === 'evidenzia') {
        event.preventDefault()
        window.getSelection()?.removeAllRanges()
      }
    }
    const textRange = (start: number, end: number) => {
      const parts = sourceParts(root).filter(p => p.node.nodeType === Node.TEXT_NODE && p.start < end && p.end > start)
      if (!parts.length) return null
      const first = parts[0], last = parts.at(-1)!
      const range = document.createRange()
      range.setStart(first.node, Math.max(0, start - first.start))
      range.setEnd(last.node, Math.min(last.text.length, end - last.start))
      return range
    }
    const onMouseUp = (event: MouseEvent | TouchEvent) => {
      if (tripleClick || ('detail' in event && event.detail >= 3) || ('button' in event && event.button !== 0)) {
        event.stopImmediatePropagation()
        if (tripleClick) window.getSelection()?.removeAllRanges()
        return
      }
      selected = null
      const selection = window.getSelection()
      if (modeRef.current === 'evidenzia' && selection?.rangeCount && !selection.isCollapsed) {
        const range = selection.getRangeAt(0)
        if (root.contains(range.commonAncestorContainer)) {
          selected = sourceOffsets(root, range)
          const { text, start, end } = selected
          if (end <= start) return
          // La libreria colora soltanto i nodi testuali: i confini possono cadere su una formula.
          const plain = textRange(start, end)
          if (plain) h.fromRange(plain)
          else {
            const id = globalThis.crypto?.randomUUID?.() ?? `rt-math-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
            const meta = { parentTagName: root.tagName, parentIndex: -2, textOffset: 0 }
            paintMath(id, colorRef.current, start, end)
            persist({ id, text: text.slice(start, end), startMeta: meta, endMeta: meta, sourceStart: start, sourceEnd: end }, colorRef.current)
          }
          selection.removeAllRanges()
          event.stopImmediatePropagation()
        }
      }
      if (modeRef.current === 'gomma' && event.target instanceof Element) {
        const id = mathId(event.target)
        if (id) remove(id)
      }
    }
    const onContextMenu = (event: MouseEvent) => {
      const id = mathId(event.target as Element) ?? h.getIdByDom(event.target as HTMLElement)
      if (!id) return
      event.preventDefault()
      remove(id)
    }
    root.addEventListener('mousedown', onMouseDown, true)
    root.addEventListener('mouseup', onMouseUp, true)
    root.addEventListener('touchend', onMouseUp as EventListener, true)
    root.addEventListener('contextmenu', onContextMenu)


    h.on(Highlighter.event.CREATE, ({ sources, type }) => {
      if (type !== 'from-input') return
      if (tripleClick) { sources.forEach(source => h.remove(source.id)); return }
      for (const source of sources) {
        const chosen = colorRef.current
        h.addClass(`rt-hl-${chosen}`, source.id)
        const doms = h.getDoms(source.id)
        const range = document.createRange()
        range.setStartBefore(doms[0])
        range.setEndAfter(doms.at(-1)!)
        const offsets = selected ?? sourceOffsets(root, range)
        const body: Stored = { startMeta: source.startMeta, endMeta: source.endMeta, text: offsets.text.slice(offsets.start, offsets.end), id: source.id,
          sourceStart: offsets.start, sourceEnd: offsets.end }
        paintMath(source.id, chosen, offsets.start, offsets.end)
        persist(body, chosen)
      }
      window.getSelection()?.removeAllRanges()
    })
    h.on(Highlighter.event.CLICK, ({ id }) => {
      if (modeRef.current !== 'gomma') return
      remove(id)
    })
    if (modeRef.current === 'evidenzia') h.run()

    highlightsApi.list(lessonId, unitId).then((rows) => {
      if (!alive) return
      for (const row of rows) {
        const source = row.source as Stored
        try {
          let start: number, end: number
          if (typeof source.sourceStart === 'number' && typeof source.sourceEnd === 'number') {
            start = source.sourceStart; end = source.sourceEnd
            const range = sourceRange(root, start, end)
            if (!range || sourceOffsets(root, range).text.slice(start, end) !== source.text) continue
            // Si ripristinano i confini dal sorgente: annotazioni e span delle note non contano.
            const plain = textRange(start, end)
            if (plain) {
              const restore = h.hooks.Serialize.Restore.tap(() => [
                { $node: plain.startContainer, offset: plain.startOffset },
                { $node: plain.endContainer, offset: plain.endOffset },
              ])
              try { h.fromStore(source.startMeta, source.endMeta, source.text, source.id) } finally { restore() }
            }
          } else {
            h.fromStore(source.startMeta, source.endMeta, source.text, source.id)
            const doms = h.getDoms(source.id)
            if (!doms.length) continue
            const range = document.createRange()
            range.setStartBefore(doms[0]); range.setEndAfter(doms.at(-1)!)
            const offsets = sourceOffsets(root, range)
            start = offsets.start; end = offsets.end
            if (offsets.text.slice(start, end) !== source.text) { h.remove(source.id); continue }
          }
          h.addClass(`rt-hl-${row.color}`, source.id)
          paintMath(source.id, row.color, start, end)
          ids.set(source.id, row.id)
          if (row.precedente) {
            // L'icona è un ::after del contenitore dell'evidenziazione (classe rt-hl-prev): nessun
            // nodo in più nel testo, e quando l'evidenziazione si toglie sparisce con lei.
            const lastDom = h.getDoms(source.id).at(-1)
            if (lastDom) {
              lastDom.classList.add('rt-hl-prev')
              lastDom.dataset.precedente = 'true'
              mountDomTooltip(lastDom, "Precedente all'ultima aggiunta di fonti")
            }
          }
        } catch {
          // Il testo dell'unità è cambiato: l'evidenziazione non si ritrova e si salta.
        }
      }
    }).catch(() => {})

    return () => {
      alive = false
      root.removeEventListener('mousedown', onMouseDown, true)
      root.removeEventListener('mouseup', onMouseUp, true)
      root.removeEventListener('touchend', onMouseUp as EventListener, true)
      root.removeEventListener('contextmenu', onContextMenu)
      h.dispose()
      for (const marks of mathMarks.values()) marks.clear()
      refreshMath()
      if (highlighter.current === h) highlighter.current = null
    }
  }, [root, lessonId, unitId])

  useEffect(() => {
    if (mode === 'evidenzia') highlighter.current?.run()
    else highlighter.current?.stop()
  }, [mode, root])

  const clear = useCallback(async () => {
    highlighter.current?.removeAll()
    clearMath.current()
    saved.current.clear()
    await highlightsApi.clear(lessonId, unitId)
  }, [lessonId, unitId])

  return { clear }
}
