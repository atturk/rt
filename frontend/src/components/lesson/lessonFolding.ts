import {
  codeFolding,
  foldGutter,
  foldable,
  foldedRanges,
  unfoldEffect,
} from '@codemirror/language'
import { EditorState, type Extension } from '@codemirror/state'
import { EditorView, ViewPlugin, type ViewUpdate } from '@codemirror/view'

/**
 * Sezioni richiudibili (folding) come in Obsidian per l'editor delle lezioni (K2):
 * - Accanto a ogni titolo (##, ###, ...) una freccia che compare al passaggio del mouse
 *   (sempre visibile su telefono) e chiude o riapre tutto fino al titolo successivo dello stesso livello o superiore.
 * - Una sezione chiusa mostra "…" alla fine del titolo; un clic sul titolo o sulla freccia la riapre.
 * - Scorciatoie: Mod-Alt-[ chiude e Mod-Alt-] riapre la sezione del cursore, Ctrl-Alt-[ chiude tutto e Ctrl-Alt-] riapre tutto.
 * - Riapertura automatica: le sezioni chiuse si riaprono da sole quando il cursore o lo scorrimento
 *   (scrollIntoView) salta a un punto dentro la sezione chiusa (unità, problema, timecode, ricerca).
 * - Il testo salvato non cambia: chiudere una sezione non modifica il Markdown né fa partire il salvataggio.
 */

const CHEVRON_DOWN_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>'

const CHEVRON_RIGHT_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-right"><path d="m9 18 6-6-6-6"/></svg>'

function createFoldMarker(open: boolean): HTMLElement {
  const marker = document.createElement('span')
  marker.className = `rt-fold-marker ${open ? 'rt-fold-open' : 'rt-fold-closed'}`
  marker.setAttribute('aria-hidden', 'true')
  marker.setAttribute('title', open ? 'Riduci sezione' : 'Espandi sezione')
  marker.innerHTML = open ? CHEVRON_DOWN_SVG : CHEVRON_RIGHT_SVG
  return marker
}

export const autoUnfoldOnJump = EditorState.transactionFilter.of((tr) => {
  const folds = foldedRanges(tr.startState)
  if (!folds.size) return tr

  const effects: any[] = []
  const unfolded = new Set<string>()

  const checkPos = (pos: number | null | undefined) => {
    if (pos == null) return
    folds.between(pos, pos, (from, to) => {
      // Si riapre solo se il punto è strettamente dentro il corpo piegato, non sul titolo stesso
      if (pos > from && pos <= to) {
        const key = `${from}:${to}`
        if (!unfolded.has(key)) {
          unfolded.add(key)
          effects.push(unfoldEffect.of({ from, to }))
        }
      }
    })
  }

  if (tr.selection) {
    checkPos(tr.selection.main.head)
    checkPos(tr.selection.main.anchor)
  }

  for (const effect of tr.effects) {
    if (effect.value && typeof effect.value === 'object' && 'range' in effect.value) {
      const range = (effect.value as { range?: { from?: number; to?: number } }).range
      if (range) {
        checkPos(range.from)
        checkPos(range.to)
      }
    }
  }

  if (effects.length === 0) return tr
  return [tr, { effects }]
})

const headingClickUnfold = EditorView.domEventHandlers({
  click: (event, view) => {
    const target = event.target as HTMLElement | null
    // Il placeholder cm-foldPlaceholder viene già gestito da CodeMirror
    if (target?.closest('.cm-foldPlaceholder')) return false

    // Se si clicca sul testo di un titolo che è attualmente chiuso, riaprilo
    const pos = view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? (target ? view.posAtDOM(target) : null)
    if (pos == null) return false

    const line = view.state.doc.lineAt(pos)
    const range = foldable(view.state, line.from, line.to)
    if (!range) return false

    let isFolded = false
    foldedRanges(view.state).between(range.from, range.to, (from, to) => {
      if (from === range.from && to === range.to) isFolded = true
    })

    if (isFolded) {
      view.dispatch({ effects: unfoldEffect.of(range) })
      return true
    }
    return false
  },
})

/** La gutter non eredita il padding del titolo: centra la freccia sulla sua prima riga. */
const alignFoldMarkers = ViewPlugin.fromClass(class {
  constructor(view: EditorView) { this.measure(view) }
  update(update: ViewUpdate) {
    if (update.geometryChanged || update.viewportChanged || update.docChanged) this.measure(update.view)
  }
  measure(view: EditorView) {
    view.requestMeasure({
      key: this,
      read: current => Array.from(current.dom.querySelectorAll<HTMLElement>('.cm-foldGutter .cm-gutterElement')).flatMap(row => {
        const marker = row.querySelector<HTMLElement>('.rt-fold-marker')
        if (!marker) return []
        const rowTop = row.getBoundingClientRect().top
        const block = current.lineBlockAtHeight(rowTop - current.documentTop + 1)
        const node = current.domAtPos(block.from).node
        const line = (node instanceof Element ? node : node.parentElement)?.closest<HTMLElement>('.cm-line')
        if (!line) return []
        const style = getComputedStyle(line)
        const lineHeight = Number.parseFloat(style.lineHeight)
        if (!Number.isFinite(lineHeight)) return []
        const center = line.getBoundingClientRect().top + Number.parseFloat(style.paddingTop || '0') + lineHeight / 2
        return [{ marker, offset: center - rowTop - marker.getBoundingClientRect().height / 2 }]
      }),
      write: positions => { for (const { marker, offset } of positions) marker.style.transform = `translateY(${offset}px)` },
    })
  }
})

export const lessonFolding: Extension = [
  codeFolding({
    placeholderText: '…',
  }),
  foldGutter({
    markerDOM: createFoldMarker,
  }),
  alignFoldMarkers,
  autoUnfoldOnJump,
  headingClickUnfold,
]
