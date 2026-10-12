import type { EditorState } from '@codemirror/state'
import type { Schemas } from '@/api/client'
import { unitRanges } from './lessonUnits'

/** Una selezione può attraversare più unità: titoli e timecode non fanno parte delle ancore. */
export function reviewSelection(state: EditorState, from: number, to: number, known: readonly string[]): Schemas['ReviewPartSelection'][] {
  if (from >= to) return []
  return unitRanges(state).flatMap(unit => {
    if (!known.includes(unit.id)) return []
    let line = state.doc.lineAt(unit.from).number + 1
    while (line <= unit.endLine && !state.doc.line(line).text.trim()) line++
    if (line <= unit.endLine && /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(state.doc.line(line).text.trim())) line++
    while (line <= unit.endLine && !state.doc.line(line).text.trim()) line++
    if (line > unit.endLine) return []
    const body = state.doc.line(line).from
    const start = Math.max(body, from), end = Math.min(unit.to, to)
    if (start >= end || !state.sliceDoc(start, end).trim()) return []
    // CodeMirror conta UTF-16; make_anchor sul server conta caratteri Unicode.
    const before = Array.from(state.sliceDoc(body, start))
    const quote = state.sliceDoc(start, end)
    return [{ unit_id: unit.id, anchor: {
      quote, prefix: before.slice(-40).join(''), suffix: Array.from(state.sliceDoc(end, unit.to)).slice(0, 40).join(''),
      start: before.length, end: before.length + Array.from(quote).length,
    } }]
  })
}
