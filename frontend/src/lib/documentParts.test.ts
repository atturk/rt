import { blockIndex, documentBlocks, headingNumber, macroOf, markdownBlocks, partOfRange, unitsOfMacro } from './documentParts'

const UNITS = ['1.1', '1.2', '2.1', '2.2', '2.3']

function article() {
  const root = document.createElement('article')
  root.innerHTML = [
    '<h1>Il ciclo cardiaco</h1>',
    '<p>Introduzione</p>',
    '<h2>1 Fasi del ciclo</h2>',
    '<h3 data-unit-id="1.1">1.1 Sistole e diastole</h3>',
    '<p data-unit-timecode="1.1">03:12</p>',
    '<p>Testo 1.1 <b>a</b></p>',
    '<h3 data-unit-id="1.2">1.2 Curva pressione-volume</h3>',
    '<p>Testo 1.2</p>',
    '<h2>2. Regolazione</h2>',
    '<p>Prima della prima subunità</p>',
    '<h3 data-unit-id="2.1">2.1 Precarico</h3>',
    '<p>Testo 2.1</p>',
    '<h3 data-unit-id="2.2">2.2 Postcarico</h3>',
    '<p>Testo 2.2</p>',
    '<h3 data-unit-id="2.3">2.3 Contrattilità</h3>',
    '<p>Testo 2.3</p>',
  ].join('')
  return root
}

describe('documentParts', () => {
  it('numeri e unità madri', () => {
    expect(macroOf('2.1')).toBe('2')
    expect(macroOf('3')).toBe('3')
    expect(macroOf('1.2.3')).toBe('1.2')
    expect(unitsOfMacro(UNITS, '2')).toEqual(['2.1', '2.2', '2.3'])
    expect(headingNumber('2 Regolazione')).toBe('2')
    expect(headingNumber('2. Regolazione')).toBe('2')
    expect(headingNumber('Regolazione')).toBeNull()
  })

  it('i blocchi sanno la loro subunità e la loro unità', () => {
    const blocks = documentBlocks(article(), UNITS)
    expect(blocks.map((b) => b.unit)).toEqual([null, null, null, '1.1', '1.1', '1.1', '1.2', '1.2', null, null, '2.1', '2.1', '2.2', '2.2', '2.3', '2.3'])
    expect(blocks[2]).toEqual({ unit: null, macro: '1', heading: 'macro' })
    expect(blocks[3].heading).toBe('unit')
    expect(blocks[0].macro).toBeNull()
  })

  it('selezione dentro una subunità: solo quella', () => {
    const root = article()
    const blocks = documentBlocks(root, UNITS)
    const bold = root.querySelector('b')!.firstChild
    const i = blockIndex(root, bold)
    expect(i).toBe(5)
    expect(partOfRange(blocks, i, i, UNITS)).toEqual(['1.1'])
  })

  it('selezione che attraversa più subunità: tutte quelle toccate, in ordine', () => {
    const blocks = documentBlocks(article(), UNITS)
    expect(partOfRange(blocks, 13, 5, UNITS)).toEqual(['1.1', '1.2', '2.1', '2.2'])
    expect(partOfRange(blocks, 11, 13, UNITS)).toEqual(['2.1', '2.2'])
  })

  it("titolo di un'unità o testo prima della sua prima subunità: l'unità intera", () => {
    const blocks = documentBlocks(article(), UNITS)
    expect(partOfRange(blocks, 8, 8, UNITS)).toEqual(['2.1', '2.2', '2.3'])
    expect(partOfRange(blocks, 9, 9, UNITS)).toEqual(['2.1', '2.2', '2.3'])
    expect(partOfRange(blocks, 2, 2, UNITS)).toEqual(['1.1', '1.2'])
  })

  it('titolo di una subunità: solo quella; titolo della lezione: niente', () => {
    const blocks = documentBlocks(article(), UNITS)
    expect(partOfRange(blocks, 6, 6, UNITS)).toEqual(['1.2'])
    expect(partOfRange(blocks, 0, 1, UNITS)).toEqual([])
  })

  it('nodi fuori dal documento', () => {
    expect(blockIndex(article(), document.createElement('p'))).toBe(-1)
  })
})

describe('markdownBlocks', () => {
  const lines = ['## 1. Unità', '', '### 1.1 Prima', '00:10', 'Testo', '### 1.2 Seconda', '01:00', 'Altro', '## 2. Altra unità', 'Intro', '### 2.1 Terza']
  const ids = ['1.1', '1.2', '2.1']

  it('assegna a ogni riga la subunità e l\'unità del titolo che la precede', () => {
    const blocks = markdownBlocks(lines, ids)
    expect(blocks[0]).toEqual({ unit: null, macro: '1', heading: 'macro' })
    expect(blocks[4]).toEqual({ unit: '1.1', macro: '1', heading: null })
    expect(blocks[5]).toEqual({ unit: '1.2', macro: '1', heading: 'unit' })
    expect(blocks[9]).toEqual({ unit: null, macro: '2', heading: null })
  })

  it('una selezione dalla 1.2 alla 2.1 vale 1.2 e 2.1; il titolo di unità la vale intera', () => {
    const blocks = markdownBlocks(lines, ids)
    expect(partOfRange(blocks, 7, 10, ids)).toEqual(['1.2', '2.1'])
    expect(partOfRange(blocks, 0, 0, ids)).toEqual(['1.1', '1.2'])
  })
})
