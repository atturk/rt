import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { lessonClassifier, setClassifier } from './lessonClassifier'
import { timecodeLock } from './timecodeLock'
const markdown = '## 1. Sezione\n### 1.1 Unità\n00:00\nAvviso organizzativo.\n### 1.2 Altra\n00:20\nTesto didattico.'
function mount() {
  const parent = document.createElement('div')
  const view = new EditorView({ parent, state: EditorState.create({ doc: markdown, extensions: [lessonClassifier, timecodeLock] }) })
  return { parent, view }
}
const unit = (id: string, score: number, effective: 'didactic' | 'organizational'): Schemas['UnitRelevanceItem'] => ({ unit_id: id, review_included: effective === 'didactic', title: '', content: '', effective, prediction: effective, answer: { score }, stale: false })
it('affianca al timecode etichetta e numero colorato, attenuando il testo non didattico', () => {
  const { parent, view } = mount()
  view.dispatch({ effects: setClassifier.of([unit('1.1', .4, 'organizational'), unit('1.2', 1.8, 'didactic')]) })
  expect(parent.querySelectorAll('.rt-unit-label')).toHaveLength(1)
  expect(parent.querySelector('.rt-unit-label')).toHaveTextContent('Informazioni organizzative')
  expect(parent.querySelector('.rt-unit-score.text-danger')).toHaveTextContent('0,4')
  expect(parent.querySelector('.rt-unit-score.text-success')).toHaveTextContent('1,8')
  expect(parent.querySelector('.rt-unit-excluded')).toHaveTextContent('Avviso organizzativo.')
  expect(view.state.doc.toString()).toBe(markdown)
  view.dispatch({ effects: setClassifier.of([]) })
  expect(parent.querySelector('.rt-unit-classification')).toBeNull()
  expect(parent.querySelector('.rt-unit-excluded')).toBeNull()
  view.destroy()
})
it('rispetta le correzioni manuali e non mostra score obsoleti', () => {
  const { parent, view } = mount()
  view.dispatch({ effects: setClassifier.of([{ ...unit('1.1', .4, 'didactic'), prediction: 'organizational', override: 'didactic', label: 'Organizzative' }, { ...unit('1.2', 1.8, 'didactic'), stale: true }]) })
  expect(parent.querySelectorAll('.rt-unit-score')).toHaveLength(1)
  expect(parent.querySelector('.rt-unit-label')).toBeNull()
  expect(parent.querySelector('.rt-unit-excluded')).toBeNull()
  view.destroy()
})
