import { EditorState } from '@codemirror/state'
import { reviewSelection } from './reviewSelection'

const doc = '## 1. Struttura\n\n### 1.1 Prima\n\n00:00\n\n😀 Prima frase. Seconda frase.\n\n### 1.2 Seconda\n\n00:10\n\nAltro testo.\n'
it('ancora sul corpo con posizioni e contesto Unicode come Python', () => {
  const from = doc.indexOf('Seconda frase'), to = from + 'Seconda frase.'.length
  const [part] = reviewSelection(EditorState.create({ doc }), from, to, ['1.1', '1.2'])
  expect(part).toEqual({ unit_id: '1.1', anchor: { quote: 'Seconda frase.', prefix: '😀 Prima frase. ', suffix: '', start: 15, end: 29 } })
})
it('divide tra le unità e lascia fuori titoli e timecode', () => {
  const parts = reviewSelection(EditorState.create({ doc }), doc.indexOf('Prima frase'), doc.indexOf('Altro testo.') + 12, ['1.1', '1.2'])
  expect(parts.map(p => p.unit_id)).toEqual(['1.1', '1.2'])
  expect(parts[0].anchor.quote).toBe('Prima frase. Seconda frase.')
  expect(parts[1].anchor.quote).toBe('Altro testo.')
  expect(parts[1].anchor.start).toBe(0)
})
it('titoli, selezioni vuote e unità non rielaborate non danno ancore', () => {
  const state = EditorState.create({ doc })
  expect(reviewSelection(state, 0, doc.indexOf('😀'), ['1.1', '1.2'])).toEqual([])
  expect(reviewSelection(state, 0, 0, ['1.1'])).toEqual([])
  expect(reviewSelection(state, 0, doc.length, [])).toEqual([])
})
