import { EditorState, type Extension, type Range, StateEffect, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view'

/**
 * Timecode protetti nell'editor della lezione: la riga sotto `### 1.1 Titolo` (12:30 o
 * 1:02:30) si vede come l'etichetta della lettura, che il cursore salta e la digitazione non
 * tocca. Un clic sposta l'audio (evento `rt-timecode-seek` con i secondi, gestito da chi monta
 * l'editor); un triplo clic la sblocca e la seleziona; uscendo dalla riga torna bloccata.
 */

const TIMECODE_RE = /^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$/
const UNIT_HEADING_RE = /^###\s/

export const SEEK_EVENT = 'rt-timecode-seek'

type Span = { from: number; to: number; text: string }

export function timecodeSeconds(text: string): number | null {
  const m = TIMECODE_RE.exec(text)
  if (!m) return null
  return Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3])
}

/** Timecode del documento: la prima riga non vuota dopo un titolo di unità, se è un timecode. */
export function timecodeSpans(state: EditorState): Span[] {
  const out: Span[] = []
  let afterHeading = false
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n)
    if (UNIT_HEADING_RE.test(line.text)) {
      afterHeading = true
      continue
    }
    if (!afterHeading || !line.text.trim()) continue
    afterHeading = false
    if (!TIMECODE_RE.test(line.text)) continue
    const lead = line.text.length - line.text.trimStart().length
    const text = line.text.trim()
    out.push({ from: line.from + lead, to: line.from + lead + text.length, text })
  }
  return out
}

const unlock = StateEffect.define<number>()

class TimecodeChip extends WidgetType {
  readonly text: string
  constructor(text: string) {
    super()
    this.text = text
  }
  eq(other: TimecodeChip) {
    return other.text === this.text
  }
  toDOM(view: EditorView) {
    const chip = document.createElement('span')
    chip.className = 'rt-timecode rt-timecode-locked'
    chip.textContent = this.text
    chip.title = 'Clic: ascolta da qui · triplo clic: modifica'
    chip.setAttribute('role', 'button')
    chip.setAttribute('aria-label', `Timecode ${this.text}: clic per ascoltare, triplo clic per modificarlo`)
    chip.addEventListener('mousedown', (event) => {
      event.preventDefault()
      if (event.detail === 1) {
        const seconds = timecodeSeconds(this.text)
        if (seconds != null) chip.dispatchEvent(new CustomEvent(SEEK_EVENT, { bubbles: true, detail: seconds }))
      }
      if (event.detail < 3) return
      const from = view.posAtDOM(chip)
      view.dispatch({ effects: unlock.of(from), selection: { anchor: from, head: from + this.text.length } })
      view.focus()
    })
    return chip
  }
  ignoreEvent() {
    return true
  }
}

type LockState = { unlocked: number | null; spans: Span[]; decorations: DecorationSet }

function build(state: EditorState, unlocked: number | null): LockState {
  const spans = timecodeSpans(state)
  const ranges: Range<Decoration>[] = []
  for (const span of spans) {
    const line = state.doc.lineAt(span.from)
    if (unlocked != null && line.from === unlocked) ranges.push(Decoration.line({ class: 'rt-timecode-editing' }).range(line.from))
    else ranges.push(Decoration.replace({ widget: new TimecodeChip(span.text) }).range(span.from, span.to))
  }
  return { unlocked, spans, decorations: Decoration.set(ranges, true) }
}

const lockField = StateField.define<LockState>({
  create: (state) => build(state, null),
  update(value, tr) {
    let unlocked = value.unlocked
    if (unlocked != null && tr.docChanged) unlocked = tr.state.doc.lineAt(tr.changes.mapPos(unlocked)).from
    for (const effect of tr.effects) if (effect.is(unlock)) unlocked = tr.state.doc.lineAt(effect.value).from
    if (unlocked != null) {
      const line = tr.state.doc.lineAt(unlocked)
      const head = tr.state.selection.main.head
      if (head < line.from || head > line.to) unlocked = null
    }
    if (!tr.docChanged && unlocked === value.unlocked) return value
    return build(tr.state, unlocked)
  },
  provide: (field) => [
    EditorView.decorations.from(field, (value) => value.decorations),
    EditorView.atomicRanges.of((view) => view.state.field(field).decorations),
  ],
})

/** Scarta le modifiche che toccano un timecode bloccato (digitazione, incolla, cancella). */
const protect = EditorState.transactionFilter.of((tr) => {
  if (!tr.docChanged) return tr
  const { unlocked, spans } = tr.startState.field(lockField)
  const locked = spans.filter((s) => unlocked == null || tr.startState.doc.lineAt(s.from).from !== unlocked)
  let touches = false
  tr.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
    if (locked.some((s) => fromA <= s.to && toA >= s.from &&
      // Andare a capo dopo il timecode non cambia la sua riga (anche a fine documento).
      !(fromA === toA && fromA === s.to && inserted.toString().startsWith('\n')))) touches = true
  })
  return touches ? [] : tr
})

export const timecodeLock: Extension = [lockField, protect]
