import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { issueRange, issuePosition, lessonReview, setReview, ISSUE_EVENT } from './lessonReview'
const markdown = '## 1. Sezione\n### 1.1 Unità\n00:00\nIl pH è 6.\n### 1.2 Altra\n00:20\nIl pH è 6.'
const item = (id: string, unit: string): Schemas['IssueItem'] => ({ issue: { id, unit_id: unit, type: 'ERR_CONCETTUALE', severity: 'high', claim: 'Il pH è 6.' } })
it('cerca soltanto nell’unità corretta e riconosce il testo riscritto', () => {
  const state = EditorState.create({ doc: markdown })
  const first = issueRange(state, item('a', '1.1'))!
  expect(state.sliceDoc(first.from, first.to)).toBe('Il pH è 6.')
  const changed = state.update({ changes: { ...first, insert: 'Il pH è 7.' } }).state
  expect(issueRange(changed, item('a', '1.1'))).toBeNull()
  expect(issueRange(changed, item('b', '1.2'))).not.toBeNull()
})
it('evidenzia l’issue selezionata, sottolinea le altre e le apre con un clic', () => {
  const parent = document.createElement('div')
  const select = vi.fn()
  parent.addEventListener(ISSUE_EVENT, (e) => select((e as CustomEvent).detail))
  const view = new EditorView({ parent, state: EditorState.create({ doc: markdown, extensions: lessonReview }) })
  view.dispatch({ effects: setReview.of({ items: [item('a', '1.1'), item('b', '1.2')], selected: 'a' }) })
  expect(parent.querySelector('.rt-issue-selected')?.textContent).toBe('Il pH è 6.')
  parent.querySelector('.rt-issue-other')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  expect(select).toHaveBeenCalledWith('b')
  view.dispatch({ effects: setReview.of({ items: [], selected: null }) })
  expect(parent.querySelector('[data-review-issue]')).toBeNull()
  view.destroy()
})

it('issue d’unità: widget al timestamp, nessun mark, selezione con clic; decise e fuori da Verifica spariscono', () => {
  const asr = { issue: { ...item('asr', '1.1').issue, type: 'ERR_ASR_ST' } }
  const drift = { issue: { ...item('drift', '1.1').issue, type: 'ERR_REWRITE_DRIFT' } }
  const parent = document.createElement('div')
  const select = vi.fn()
  parent.addEventListener(ISSUE_EVENT, e => select((e as CustomEvent).detail))
  const view = new EditorView({ parent, state: EditorState.create({ doc: markdown, extensions: lessonReview }) })
  view.dispatch({ effects: setReview.of({ items: [asr, drift], selected: 'asr' }) })
  expect(issuePosition(view.state, asr)).toBe(view.state.doc.line(3).to)
  const buttons = parent.querySelectorAll('button[data-review-issue]')
  expect(buttons).toHaveLength(2)
  expect(parent.querySelector('span.rt-issue-other, span.rt-issue-selected')).toBeNull()
  expect(buttons[0]).toHaveAttribute('aria-label', 'Qualità ASR · statistica')
  expect(buttons[0]).toHaveClass('rt-issue-selected')
  expect(buttons[1]).toHaveAttribute('title', 'Fedeltà al parlato')
  buttons[1].dispatchEvent(new MouseEvent('click', { bubbles: true }))
  expect(select).toHaveBeenCalledWith('drift')
  view.dispatch({ effects: setReview.of({ items: [{ ...asr, decision: { issue_id: 'asr', decision: 'accepted', resolved_by: 'user', timestamp: '' } }], selected: null }) })
  expect(parent.querySelector('[data-review-issue]')).toBeNull()
  view.dispatch({ effects: setReview.of({ items: [], selected: null }) })
  expect(parent.querySelector('[data-review-issue]')).toBeNull()
  view.destroy()
})
