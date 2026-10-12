import { EditorState, StateEffect, StateField, type Range } from '@codemirror/state'
import { Decoration, EditorView, type DecorationSet } from '@codemirror/view'
import { unitRanges } from './lessonUnits'
import type { StudyNote } from '@/api/studyNotes'

export const STUDY_NOTE_EVENT = 'rt-study-note'

type NotesState = { notes: StudyNote[]; selected: number | null }
export const setStudyNotes = StateEffect.define<NotesState>()

export function noteRange(state: EditorState, note: StudyNote): { from: number; to: number } | null {
  if (note.anchor_state === 'non_ritrovata') return null
  const unit = unitRanges(state).find((u) => u.id === note.unit_id)
  if (!unit) return null

  let line = state.doc.lineAt(unit.from).number + 1
  while (line <= unit.endLine && !state.doc.line(line).text.trim()) line++
  if (line <= unit.endLine) line++ // timecode
  const from = line <= unit.endLine ? state.doc.line(line).from : unit.to
  const content = state.sliceDoc(from, unit.to)

  const quote = (note.current_quote || (note.anchor as { quote?: string } | undefined)?.quote || '').trim()
  if (!quote) return null

  const escaped = quote.split(/\s+/).map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')
  const matches = [...content.matchAll(new RegExp(escaped, 'g'))]
  if (!matches.length) return null

  const anchor = note.anchor as { quote: string; prefix?: string; suffix?: string; start?: number; end?: number } | undefined
  const score = (at: number, length: number) => {
    if (!anchor) return 0
    let same = 0
    if (anchor.prefix) {
      for (let i = 1; i <= anchor.prefix.length; i++) {
        if (content[at - i] !== anchor.prefix.at(-i)) break
        same++
      }
    }
    if (anchor.suffix) {
      for (let i = 0; i < anchor.suffix.length; i++) {
        if (content[at + length + i] !== anchor.suffix[i]) break
        same++
      }
    }
    return same
  }

  matches.sort(
    (a, b) =>
      score(b.index, b[0].length) - score(a.index, a[0].length) ||
      Math.abs(a.index - (anchor?.start ?? 0)) - Math.abs(b.index - (anchor?.start ?? 0)),
  )
  const match = matches[0]
  return match ? { from: from + match.index, to: from + match.index + match[0].length } : null
}

function decorations(state: EditorState, notesState: NotesState): DecorationSet {
  const ranges: Range<Decoration>[] = []
  for (const note of notesState.notes) {
    const range = noteRange(state, note)
    if (!range || range.from >= range.to) continue

    const isSelected = note.id === notesState.selected
    let cls = 'rt-sn ' + (note.kind === 'verifica' ? 'rt-sn-v' : 'rt-sn-c')
    if (note.kind === 'verifica' && note.response?.esito === 'errato') cls += ' rt-sn-bad'
    if (note.anchor_state === 'cambiata') cls += ' rt-sn-changed'
    if (isSelected) cls += ' rt-sn-selected'

    ranges.push(
      Decoration.mark({
        class: cls,
        attributes: { 'data-study-note': String(note.id) },
      }).range(range.from, range.to),
    )
  }
  return Decoration.set(ranges, true)
}

const field = StateField.define<{ notesState: NotesState; decorations: DecorationSet }>({
  create: () => ({ notesState: { notes: [], selected: null }, decorations: Decoration.none }),
  update(value, tr) {
    let notesState = value.notesState
    for (const effect of tr.effects) if (effect.is(setStudyNotes)) notesState = effect.value
    return tr.docChanged || notesState !== value.notesState
      ? { notesState, decorations: decorations(tr.state, notesState) }
      : value
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.decorations),
})

export const lessonStudyNotes = [
  field,
  EditorView.domEventHandlers({
    mousedown(event) {
      const mark = (event.target as HTMLElement).closest<HTMLElement>('[data-study-note]')
      if (!mark?.dataset.studyNote) return false
      mark.dispatchEvent(new CustomEvent(STUDY_NOTE_EVENT, { bubbles: true, detail: Number(mark.dataset.studyNote) }))
      return false
    },
  }),
]
