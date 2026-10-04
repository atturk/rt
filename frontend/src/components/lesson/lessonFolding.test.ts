import { markdown } from '@codemirror/lang-markdown'
import {
  foldable,
  foldAll,
  foldCode,
  foldEffect,
  foldedRanges,
  unfoldAll,
  unfoldCode,
  unfoldEffect,
} from '@codemirror/language'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { afterEach, describe, expect, it } from 'vitest'

import { lessonFolding } from './lessonFolding'

if (typeof Range !== 'undefined') {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => ({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    toJSON: () => {},
  } as DOMRect)
}

const views: EditorView[] = []

function createView(doc: string) {
  const state = EditorState.create({
    doc,
    extensions: [markdown(), lessonFolding],
  })
  const view = new EditorView({ state })
  views.push(view)
  return view
}

afterEach(() => {
  while (views.length > 0) {
    views.pop()?.destroy()
  }
})

const DOC = `## 1. Introduzione

Primo paragrafo della sezione.

### 1.1 Concetti chiave

Dettagli e spiegazioni dell'unità.

## 2. Seconda sezione

Contenuto della seconda sezione.`

describe('lessonFolding - Sezioni richiudibili (K2)', () => {
  it('chiudi e riapri: il testo del documento non cambia mai', () => {
    const view = createView(DOC)
    const l1 = view.state.doc.line(1)
    const range = foldable(view.state, l1.from, l1.to)
    expect(range).not.toBeNull()

    // Chiudi la sezione
    view.dispatch({ effects: foldEffect.of(range!) })
    expect(foldedRanges(view.state).size).toBeGreaterThan(0)
    expect(view.state.doc.toString()).toBe(DOC) // Il Markdown salvato non cambia

    // Riapri la sezione
    view.dispatch({ effects: unfoldEffect.of(range!) })
    expect(foldedRanges(view.state).size).toBe(0)
    expect(view.state.doc.toString()).toBe(DOC)
  })

  it('scorciatoie di ripiegamento: foldCode e unfoldCode agiscono sulla sezione corrente', () => {
    const view = createView(DOC)
    // Cursore dentro la prima sezione
    view.dispatch({ selection: { anchor: 5, head: 5 } })

    const folded = foldCode(view)
    expect(folded).toBe(true)
    expect(foldedRanges(view.state).size).toBeGreaterThan(0)
    expect(view.state.doc.toString()).toBe(DOC)

    const unfolded = unfoldCode(view)
    expect(unfolded).toBe(true)
    expect(foldedRanges(view.state).size).toBe(0)
  })

  it('foldAll e unfoldAll chiudono e riaprono tutte le sezioni', () => {
    const view = createView(DOC)
    foldAll(view)
    expect(foldedRanges(view.state).size).toBeGreaterThan(1)
    expect(view.state.doc.toString()).toBe(DOC)

    unfoldAll(view)
    expect(foldedRanges(view.state).size).toBe(0)
    expect(view.state.doc.toString()).toBe(DOC)
  })

  it('salto con selezione dentro una sezione chiusa: la riapre da sola', () => {
    const view = createView(DOC)
    const l1 = view.state.doc.line(1)
    const range = foldable(view.state, l1.from, l1.to)!

    // Chiudi la sezione
    view.dispatch({ effects: foldEffect.of(range) })
    expect(foldedRanges(view.state).size).toBeGreaterThan(0)

    // Se il cursore si sposta sul titolo, resta chiusa
    view.dispatch({ selection: { anchor: 3, head: 3 } })
    expect(foldedRanges(view.state).size).toBeGreaterThan(0)

    // Se si salta a un punto dentro la sezione chiusa (es. testo dell'unità)
    const posInside = DOC.indexOf('Dettagli e spiegazioni')
    view.dispatch({ selection: { anchor: posInside, head: posInside } })

    // La sezione si è riaperta automaticamente!
    expect(foldedRanges(view.state).size).toBe(0)
    expect(view.state.doc.toString()).toBe(DOC)
  })

  it('salto con scrollIntoView dentro una sezione chiusa: la riapre da sola', () => {
    const view = createView(DOC)
    const l1 = view.state.doc.line(1)
    const range = foldable(view.state, l1.from, l1.to)!

    // Chiudi la sezione
    view.dispatch({ effects: foldEffect.of(range) })
    expect(foldedRanges(view.state).size).toBeGreaterThan(0)

    // Salto come fa l'app per unità, timecode o problemi: EditorView.scrollIntoView
    const posInside = DOC.indexOf('Primo paragrafo')
    view.dispatch({ effects: EditorView.scrollIntoView(posInside, { y: 'center' }) })

    // La sezione si è riaperta automaticamente!
    expect(foldedRanges(view.state).size).toBe(0)
    expect(view.state.doc.toString()).toBe(DOC)
  })

  it('sezioni annidate: saltare nel corpo di un’unità chiusa dentro una sezione chiusa le riapre', () => {
    const view = createView(DOC)
    const lineUnit = view.state.doc.line(5) // ### 1.1 Concetti chiave
    const rChild = foldable(view.state, lineUnit.from, lineUnit.to)!
    view.dispatch({ effects: foldEffect.of(rChild) })

    const lineSec = view.state.doc.line(1) // ## 1. Introduzione
    const rParent = foldable(view.state, lineSec.from, lineSec.to)!
    view.dispatch({ effects: foldEffect.of(rParent) })

    expect(foldedRanges(view.state).size).toBeGreaterThanOrEqual(2)

    // Salto dentro il testo dell'unità
    const targetPos = DOC.indexOf('Dettagli e spiegazioni')
    view.dispatch({ selection: { anchor: targetPos, head: targetPos } })

    // Entrambe le sezioni contenenti il punto vengono riaperte
    expect(foldedRanges(view.state).size).toBe(0)
  })
})
