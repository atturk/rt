import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { lessonUnits, setUnitTasks, unitRanges } from './lessonUnits'
import { timecodeLock } from './timecodeLock'

it('affianca gli stati ai titoli e lo scheletro all’unità corrente senza modificare il Markdown', () => {
  const markdown = '## 1. Sezione\n### 1.1 Prima\n00:00\nTesto.\n### 1.2 Seconda\n\n### 1.3 Terza'
  const parent = document.createElement('div')
  const view = new EditorView({ parent, state: EditorState.create({ doc: markdown, extensions: [lessonUnits, timecodeLock] }) })
  view.dispatch({ effects: setUnitTasks.of(Object.fromEntries((['done', 'working', 'waiting'] as const).map((state, i) => {
    const element = document.createElement('span'); element.textContent = state
    return [`1.${i + 1}`, { state, element }]
  }))) })
  expect(parent.querySelector('[data-task="done"]')).toHaveTextContent('done')
  expect(parent.querySelector('[data-task="working"]')).toHaveTextContent('working')
  expect(parent.querySelector('.rt-unit-waiting')).toHaveTextContent('Terza')
  expect(parent.querySelectorAll('.rt-unit-pending > div')).toHaveLength(3)
  expect(parent.querySelector('.rt-timecode')).toHaveTextContent('00:00')
  expect(view.state.doc.toString()).toBe(markdown)
  view.dispatch({ effects: setUnitTasks.of({}) })
  expect(parent.querySelector('.rt-unit-pending')).toBeNull()
  expect(parent.querySelector('[data-task]')).toBeNull()
  view.destroy()
})

it('un titolo senza numero dentro un\'unità non la chiude (come per il server)', () => {
  const doc = '## 1. Sezione\n\n### 1.1 Prima\n\n00:00\n\nTesto.\n\n### Approfondimento\n\nAncora 1.1.\n\n### 1.2 Seconda\n\n00:10\n\nAltro.'
  const ranges = unitRanges(EditorState.create({ doc }))
  expect(ranges.map((r) => r.id)).toEqual(['1.1', '1.2'])
  expect(doc.slice(ranges[0].from, ranges[0].to)).toContain('Ancora 1.1.')
})
