import { type EditorState, type Extension, type Range, StateEffect, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, ViewPlugin, WidgetType } from '@codemirror/view'

import { DELIMITED, delimiters, loadTemml, mathElement, type Temml } from '@/lib/math'

export type MathRange = { from: number; to: number; source: string; display: boolean; block: boolean }

/** Righe dentro un blocco di codice (``` o ~~~): le formule lì dentro restano testo. */
function fencedLines(state: EditorState): Set<number> {
  const inside = new Set<number>()
  let fence: string | null = null
  for (let n = 1; n <= state.doc.lines; n++) {
    const text = state.doc.line(n).text
    const open = /^\s{0,3}(`{3,}|~{3,})/.exec(text)
    if (fence) {
      inside.add(n)
      if (open && open[1][0] === fence[0] && open[1].length >= fence.length) fence = null
      continue
    }
    if (open) {
      fence = open[1]
      inside.add(n)
    }
  }
  return inside
}

/** Formule del documento: `$$…$$`, `\[…\]`, `\(…\)` e `$…$`, fuori dai blocchi di codice. */
export function mathRanges(state: EditorState): MathRange[] {
  const text = state.doc.toString()
  const fenced = fencedLines(state)
  const out: MathRange[] = []
  for (const match of text.matchAll(DELIMITED)) {
    const from = match.index ?? 0
    const to = from + match[0].length
    const line = state.doc.lineAt(from)
    if (fenced.has(line.number) || fenced.has(state.doc.lineAt(to).number)) continue
    // Il codice in riga (`$x$`) resta testo: conta gli apici prima della formula sulla stessa riga.
    const before = line.text.slice(0, from - line.from)
    if ((before.match(/`/g)?.length ?? 0) % 2 === 1) continue
    const [source, display] = delimiters(match[0])
    if (!source.trim()) continue
    const block = display && line.from === from && state.doc.lineAt(to).to === to
    out.push({ from, to, source, display, block })
  }
  return out
}

class MathWidget extends WidgetType {
  readonly temml: Temml
  readonly source: string
  readonly display: boolean
  readonly block: boolean
  constructor(temml: Temml, source: string, display: boolean, block: boolean) {
    super()
    this.temml = temml
    this.source = source
    this.display = display
    this.block = block
  }
  eq(other: MathWidget) {
    return other.temml === this.temml && other.source === this.source && other.display === this.display && other.block === this.block
  }
  toDOM() {
    const wrap = document.createElement(this.block ? 'div' : 'span')
    wrap.className = this.block ? 'rt-editor-math rt-editor-math-block' : 'rt-editor-math'
    wrap.append(mathElement(this.temml, this.source, this.display, this.source))
    return wrap
  }
  // Il clic arriva a CodeMirror, che porta il cursore nella formula: i segni tornano e si modifica.
  ignoreEvent() {
    return false
  }
}

const setTemml = StateEffect.define<Temml>()

function build(state: EditorState, temml: Temml | null): DecorationSet {
  if (!temml) return Decoration.none
  const ranges: Range<Decoration>[] = []
  for (const math of mathRanges(state)) {
    // Come in Obsidian: con il cursore (o la selezione) sulla formula si rivede il LaTeX.
    if (state.selection.ranges.some((r) => r.to >= math.from && r.from <= math.to)) continue
    const widget = new MathWidget(temml, math.source, math.display, math.block)
    ranges.push(Decoration.replace({ widget, block: math.block }).range(math.from, math.to))
  }
  return Decoration.set(ranges, true)
}

type MathState = { temml: Temml | null; decorations: DecorationSet }

const mathField = StateField.define<MathState>({
  create: () => ({ temml: null, decorations: Decoration.none }),
  update(value, tr) {
    const temml = tr.effects.find((e) => e.is(setTemml))?.value ?? value.temml
    if (temml === value.temml && !tr.docChanged && !tr.selection) return value
    return { temml, decorations: build(tr.state, temml) }
  },
  provide: (field) => [
    EditorView.decorations.from(field, (value) => value.decorations),
    EditorView.atomicRanges.of((view) => view.state.field(field).decorations),
  ],
})

/**
 * Formule nell'editor della lezione: il LaTeX fra delimitatori si vede reso (MathML di Temml),
 * come nella lettura, e torna in chiaro quando il cursore ci entra. Temml si carica solo se il
 * documento ha formule, fuori dal bundle principale.
 */
export const lessonMath: Extension = [
  mathField,
  ViewPlugin.define((view) => {
    let asked = false
    const load = (v: EditorView) => {
      if (asked || v.state.field(mathField).temml || mathRanges(v.state).length === 0) return
      asked = true
      void loadTemml().then((temml) => v.dispatch({ effects: setTemml.of(temml) })).catch(() => { asked = false })
    }
    load(view)
    return { update: (update) => { if (update.docChanged || !asked) load(update.view) } }
  }),
]
