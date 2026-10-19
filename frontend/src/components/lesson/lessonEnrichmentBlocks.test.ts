import { EditorState } from '@codemirror/state'
import { describe, expect, it } from 'vitest'

import { generatedRanges } from './lessonEnrichmentBlocks'

describe('generatedRanges', () => {
  it('copre il blocco generato a righe intere', () => {
    const block = '<!-- rt-enrichment:start:dd17 -->\n![Elemento grafico](assets/enrichment/a.png)\n\n[Apri la visualizzazione interattiva](assets/enrichment/a.html)\n<!-- rt-enrichment:end -->\n'
    const doc = `Testo prima.\n\n${block}\nTesto dopo.`
    const state = EditorState.create({ doc })
    const [range] = generatedRanges(state)
    expect(doc.slice(range.from, range.to)).toBe(block)
    expect(doc.slice(range.to)).toBe('\nTesto dopo.')
  })

  it('senza blocchi non copre niente', () => {
    expect(generatedRanges(EditorState.create({ doc: '<!-- un commento -->\ntesto' }))).toEqual([])
  })
})
