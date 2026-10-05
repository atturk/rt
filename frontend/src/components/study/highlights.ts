import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import Highlighter from 'web-highlighter'

import { highlightsApi } from '@/api/highlights'

export type HighlightMode = 'evidenzia' | 'gomma'
export const HIGHLIGHT_COLORS = ['giallo', 'verde', 'azzurro', 'rosa', 'arancio'] as const

type Stored = { startMeta: Parameters<Highlighter['fromStore']>[0]; endMeta: Parameters<Highlighter['fromStore']>[1]; text: string; id: string }

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
  const saved = useRef(new Map<string, number>())
  const modeRef = useRef(mode)
  const colorRef = useRef(color)
  useLayoutEffect(() => {
    modeRef.current = mode
    colorRef.current = color
  }, [mode, color])

  useEffect(() => {
    if (!root) return
    const h = new Highlighter({ $root: root, wrapTag: 'span', exceptSelectors: ['.katex', 'img', 'table'], style: { className: 'rt-hl' } })
    const ids = new Map<string, number>()
    highlighter.current = h
    saved.current = ids
    let alive = true

    h.on(Highlighter.event.CREATE, ({ sources, type }) => {
      if (type !== 'from-input') return
      for (const source of sources) {
        const chosen = colorRef.current
        h.addClass(`rt-hl-${chosen}`, source.id)
        const body: Stored = { startMeta: source.startMeta, endMeta: source.endMeta, text: source.text, id: source.id }
        highlightsApi.add(lessonId, { unit_id: unitId, color: chosen, source: body })
          .then((row) => { if (alive) ids.set(source.id, row.id) })
          .catch(() => { if (alive) h.remove(source.id) })
      }
      window.getSelection()?.removeAllRanges()
    })
    h.on(Highlighter.event.CLICK, ({ id }) => {
      if (modeRef.current !== 'gomma') return
      h.remove(id)
      const row = ids.get(id)
      ids.delete(id)
      if (row !== undefined) void highlightsApi.remove(lessonId, row).catch(() => {})
    })
    if (modeRef.current === 'evidenzia') h.run()

    highlightsApi.list(lessonId, unitId).then((rows) => {
      if (!alive) return
      for (const row of rows) {
        const source = row.source as Stored
        try {
          h.fromStore(source.startMeta, source.endMeta, source.text, source.id)
          const text = h.getDoms(source.id).map((node) => node.textContent).join('')
          if (text !== source.text) {
            h.remove(source.id)
            continue
          }
          h.addClass(`rt-hl-${row.color}`, source.id)
          ids.set(source.id, row.id)
        } catch {
          // Il testo dell'unità è cambiato: l'evidenziazione non si ritrova e si salta.
        }
      }
    }).catch(() => {})

    return () => {
      alive = false
      h.dispose()
      if (highlighter.current === h) highlighter.current = null
    }
  }, [root, lessonId, unitId])

  useEffect(() => {
    if (mode === 'evidenzia') highlighter.current?.run()
    else highlighter.current?.stop()
  }, [mode, root])

  const clear = useCallback(async () => {
    highlighter.current?.removeAll()
    saved.current.clear()
    await highlightsApi.clear(lessonId, unitId)
  }, [lessonId, unitId])

  return { clear }
}
