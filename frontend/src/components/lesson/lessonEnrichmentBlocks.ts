import { type EditorState, type Extension, type Range, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView } from '@codemirror/view'

/** Blocco che build aggiunge per ogni elemento dell'arricchimento (enrichment_service.document_blocks). */
const GENERATED = /<!-- rt-enrichment:start:[a-f0-9]+ -->[\s\S]*?<!-- rt-enrichment:end -->\n?/g

/** Righe intere dei blocchi generati: nel testo non si modificano, l'elemento si vede nel suo riquadro. */
export function generatedRanges(state: EditorState): { from: number; to: number }[] {
  const text = state.doc.toString()
  const out: { from: number; to: number }[] = []
  for (const match of text.matchAll(GENERATED)) {
    const start = match.index ?? 0
    const from = state.doc.lineAt(start).from
    const end = start + match[0].length
    const to = Math.min(state.doc.lineAt(Math.max(start, end - 1)).to + (match[0].endsWith('\n') ? 1 : 0), state.doc.length)
    out.push({ from, to })
  }
  return out
}

function build(state: EditorState): DecorationSet {
  const ranges: Range<Decoration>[] = generatedRanges(state).map(({ from, to }) => Decoration.replace({ block: true }).range(from, to))
  return Decoration.set(ranges, true)
}

const field = StateField.define<DecorationSet>({
  create: build,
  update: (value, tr) => (tr.docChanged ? build(tr.state) : value),
  provide: (f) => [EditorView.decorations.from(f), EditorView.atomicRanges.of((view) => view.state.field(f))],
})

/** Nasconde nell'editor i commenti e il link dei blocchi dell'arricchimento: restano nel file. */
export const lessonEnrichmentBlocks: Extension = field
