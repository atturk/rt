import { EditorState } from '@codemirror/state'

import { unitRanges } from './lessonUnits'
import { timecodeLock, timecodeSeconds, timecodeSpans } from './timecodeLock'

const DOC = '## 1. Sezione\n### 1.1 Unità\n\n12:30\n\nTesto dell\'unità.\n### 1.2 Altra\n1:02:03\nAltro testo 10:00.\n'

describe('timecodeLock', () => {
  it('trova solo il timecode sotto ogni titolo di unità', () => {
    const spans = timecodeSpans(EditorState.create({ doc: DOC }))
    expect(spans.map((s) => s.text)).toEqual(['12:30', '1:02:03'])
  })

  it('scarta le modifiche che toccano un timecode bloccato e lascia passare il resto', () => {
    const state = EditorState.create({ doc: DOC, extensions: timecodeLock })
    const at = DOC.indexOf('12:30')
    expect(state.update({ changes: { from: at, to: at + 2, insert: '13' } }).state.doc.toString()).toBe(DOC)
    expect(state.update({ changes: { from: at + 5, to: at + 6 } }).state.doc.toString()).toBe(DOC)
    const text = DOC.indexOf('Testo')
    expect(state.update({ changes: { from: text, insert: 'Nuovo ' } }).state.doc.toString()).toContain('Nuovo Testo')
  })

  it('permette un nuovo paragrafo dopo il timecode a fine documento, mantenendone il testo', () => {
    const doc = '### 1.1 Unità\n12:30'
    const state = EditorState.create({ doc, extensions: timecodeLock })
    expect(state.update({ changes: { from: doc.length, insert: '\n\nTesto.' } }).state.doc.toString()).toBe(doc + '\n\nTesto.')
    expect(state.update({ changes: { from: doc.length, insert: '0' } }).state.doc.toString()).toBe(doc)
  })
})

describe('unitRanges', () => {
  it('ogni unità va dal suo titolo all\'ultima riga non vuota prima del titolo successivo', () => {
    const state = EditorState.create({ doc: DOC })
    const units = unitRanges(state)
    expect(units.map((u) => u.id)).toEqual(['1.1', '1.2'])
    expect(state.sliceDoc(units[0].from, units[0].to)).toBe("### 1.1 Unità\n\n12:30\n\nTesto dell'unità.")
    expect(state.sliceDoc(units[1].from, units[1].to)).toBe('### 1.2 Altra\n1:02:03\nAltro testo 10:00.')
  })

  it('timecodeSeconds legge MM:SS e H:MM:SS', () => {
    expect(timecodeSeconds('12:30')).toBe(750)
    expect(timecodeSeconds('1:02:03')).toBe(3723)
    expect(timecodeSeconds('testo')).toBeNull()
  })
})
