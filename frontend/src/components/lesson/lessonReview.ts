import { mountDomTooltip, unmountDomTooltip } from '@/components/ui/dom-tooltip'
import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { EditorState, StateEffect, StateField, type Range } from '@codemirror/state'
import { Decoration, EditorView, type DecorationSet, WidgetType } from '@codemirror/view'
import { unitRanges } from './lessonUnits'
import { issueOf, issueLabels, paragraphIssue, paragraphIssueIcon, type IssueItem } from './reviewIssues'

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

/** Le issue d’unità si raggiungono dal timestamp, senza segnare tutto il testo. */
export function issuePosition(state: EditorState, item: IssueItem): number | null {
  if (!paragraphIssue(issueOf(item))) return issueRange(state, item)?.from ?? null
  const issue = issueOf(item)
  const unit = unitRanges(state).find(u => u.id === (issue.unit_id ?? item.context?.unit_info?.split(' ')[0]))
  if (!unit) return null
  let line = state.doc.lineAt(unit.from).number + 1
  while (line <= unit.endLine && !state.doc.line(line).text.trim()) line++
  return line <= unit.endLine ? state.doc.line(line).to : null
}

class UnitIssueWidget extends WidgetType {
  private roots = new WeakMap<HTMLElement, Root>()
  readonly item: IssueItem
  readonly selected: boolean
  constructor(item: IssueItem, selected: boolean) { super(); this.item = item; this.selected = selected }
  eq(other: UnitIssueWidget) {
    return issueOf(this.item).id === issueOf(other.item).id && issueOf(this.item).type === issueOf(other.item).type && this.selected === other.selected
  }
  toDOM() {
    const issue = issueOf(this.item)
    const button = document.createElement('button')
    button.type = 'button'
    button.className = `rt-unit-issue${this.selected ? ' rt-issue-selected' : ''}`
    button.dataset.reviewIssue = issue.id
    button.setAttribute('aria-label', issueLabels[issue.type] ?? issue.type)
    button.addEventListener('click', () => button.dispatchEvent(new CustomEvent(ISSUE_EVENT, { bubbles: true, detail: issue.id })))
    const root = createRoot(button)
    root.render(createElement(paragraphIssueIcon(issue), { size: 16, 'aria-hidden': true }))
    mountDomTooltip(button, issueLabels[issue.type] ?? issue.type)
    this.roots.set(button, root)
    return button
  }
  destroy(node: HTMLElement) {
    unmountDomTooltip(node)
    const root = this.roots.get(node)
    queueMicrotask(() => root?.unmount())
  }
  ignoreEvent() { return true }
}

function decorations(state: EditorState, review: Review): DecorationSet {
  const ranges: Range<Decoration>[] = []
  for (const item of review.items) {
    if (item.decision) continue
    if (paragraphIssue(issueOf(item))) {
      const position = issuePosition(state, item)
      if (position !== null) ranges.push(Decoration.widget({ widget: new UnitIssueWidget(item, issueOf(item).id === review.selected), side: 1 }).range(position))
      continue
    }
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
