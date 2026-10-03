import { EditorState, StateEffect, StateField, type Range } from '@codemirror/state'
import { Decoration, EditorView, type DecorationSet } from '@codemirror/view'
import { unitRanges } from './lessonUnits'
import { issueOf, paragraphIssue, type IssueItem } from './reviewIssues'

export const ISSUE_EVENT = 'rt-review-issue'
type Review = { items: IssueItem[]; selected: string | null }
export const setReview = StateEffect.define<Review>()

/** Cerca nella sola unità dell'issue: un'affermazione uguale altrove non è il suo passaggio. */
export function issueRange(state: EditorState, item: IssueItem): { from: number; to: number } | null {
  const issue = issueOf(item)
  const unit = unitRanges(state).find((u) => u.id === (issue.unit_id ?? item.context?.unit_info?.split(' ')[0]))
  if (!unit) return null
  let line = state.doc.lineAt(unit.from).number + 1
  while (line <= unit.endLine && !state.doc.line(line).text.trim()) line++
  if (line <= unit.endLine) line++ // timecode
  const from = line <= unit.endLine ? state.doc.line(line).from : unit.to
  const content = state.sliceDoc(from, unit.to)
  if (paragraphIssue(issue)) return content.trim() ? { from, to: unit.to } : null
  const claim = issue.claim.trim()
  const at = claim ? content.indexOf(claim) : -1
  return at < 0 ? null : { from: from + at, to: from + at + claim.length }
}

function decorations(state: EditorState, review: Review): DecorationSet {
  const ranges: Range<Decoration>[] = []
  for (const item of review.items) {
    if (item.decision) continue
    const range = issueRange(state, item)
    if (!range || range.from >= range.to) continue
    ranges.push(Decoration.mark({ class: issueOf(item).id === review.selected ? 'rt-issue-selected' : 'rt-issue-other', attributes: { 'data-review-issue': issueOf(item).id } }).range(range.from, range.to))
  }
  return Decoration.set(ranges, true)
}
const field = StateField.define<{ review: Review; decorations: DecorationSet }>({
  create: () => ({ review: { items: [], selected: null }, decorations: Decoration.none }),
  update(value, tr) {
    let review = value.review
    for (const effect of tr.effects) if (effect.is(setReview)) review = effect.value
    return tr.docChanged || review !== value.review ? { review, decorations: decorations(tr.state, review) } : value
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.decorations),
})
export const lessonReview = [field, EditorView.domEventHandlers({
  mousedown(event) {
    const mark = (event.target as HTMLElement).closest<HTMLElement>('[data-review-issue]')
    if (!mark?.dataset.reviewIssue) return false
    mark.dispatchEvent(new CustomEvent(ISSUE_EVENT, { bubbles: true, detail: mark.dataset.reviewIssue }))
    return false
  },
})]
