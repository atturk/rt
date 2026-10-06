import { describe, expect, it } from 'vitest'

import {
  endsSentence, focusIndex, formulaMetrics, graveWord, isFullStop, nextSentence, previousSentence, readUnitWords, remainingSeconds,
  surrounding, wordDelay, type Word,
} from './rsvp'

const words = (text: string): Word[] => text.split(' ').map((t) => ({ text: t, para: 0 }))

describe('lettura veloce', () => {
  it('due soli stati: la virgola chiude solo con l’opzione', () => {
    expect(endsSentence('fine.')).toBe(true)
    expect(endsSentence('davvero?»')).toBe(true)
    expect(endsSentence('così…')).toBe(true)
    expect(isFullStop('virgola,', false)).toBe(false)
    expect(isFullStop('virgola,', true)).toBe(true)
    expect(isFullStop('elenco:', true)).toBe(true)
    expect(isFullStop('parola', true)).toBe(false)
  })

  it('tempi: base, parole lunghe, pausa a fine frase, ripartenza graduale', () => {
    const prefs = { wpm: 300, pauseMs: 400, comma: false }
    expect(wordDelay('rene', prefs)).toBe(200)
    expect(wordDelay('fisiopatologia', prefs)).toBeCloseTo(200 * (1 + 6 * 0.06))
    expect(wordDelay('rene.', prefs)).toBe(600)
    expect(wordDelay('rene,', prefs)).toBe(200)
    expect(wordDelay('rene,', { ...prefs, comma: true })).toBe(600)
    expect(wordDelay('rene', prefs, 5)).toBeCloseTo(200 * 1.6)
  })

  it('lettera di fuoco al 25, 35 o 50 % delle lettere, punteggiatura esclusa', () => {
    expect(focusIndex('fisiologia', 'prima')).toBe(2)
    expect(focusIndex('fisiologia', 'bilanciata')).toBe(3)
    expect(focusIndex('fisiologia', 'dopo')).toBe(5)
    expect(focusIndex('«rene»', 'bilanciata')).toBe(2)
    expect(focusIndex('a', 'dopo')).toBe(0)
  })

  it('frase precedente e successiva', () => {
    const w = words('Uno due. Tre quattro cinque. Sei.')
    expect(nextSentence(w, 0)).toBe(2)
    expect(nextSentence(w, 3)).toBe(5)
    expect(previousSentence(w, 4)).toBe(2)
    expect(previousSentence(w, 2)).toBe(0)
    expect(previousSentence(w, 0)).toBe(0)
  })

  it('testo intorno: la frase prima sopra, il resto sotto, massimo 12 parole', () => {
    const w = words('Prima frase. Il rene filtra il sangue ogni giorno. Dopo.')
    expect(surrounding(w, 4)).toEqual({ before: 'Il rene', after: 'il sangue ogni giorno.' })
    expect(surrounding(w, 2).before).toBe('')
    const long = words(Array.from({ length: 30 }, (_, i) => `p${i}`).join(' '))
    expect(surrounding(long, 20).before.split(' ')).toHaveLength(12)
  })

  it('tempo che manca', () => {
    expect(remainingSeconds(301, 0, 300)).toBe(60)
    expect(remainingSeconds(10, 9, 300)).toBe(0)
  })

  it('legge testo e formule, conservando i segnaposto di immagini e tabelle', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>Il <b>pa</b>rametro <span class="katex">x^2</span> cresce.</p>'
      + '<p>Vedi <img alt="grafico"> sotto.</p><table><tr><td>cella</td></tr></table><ul><li>Fine.</li></ul>'
    const { words: read, paragraphs } = readUnitWords(root)
    expect(read.map((w) => w.text)).toEqual(['Il', 'parametro', 'x^2', 'cresce.', 'Vedi', 'sotto.', 'Fine.'])
    expect(read.map((w) => w.para)).toEqual([0, 0, 0, 0, 1, 1, 3])
    expect(paragraphs[0].map((p) => p.text)).toEqual(['Il', 'parametro', 'x^2', 'cresce.'])
    expect(paragraphs[1].map((p) => p.text)).toEqual(['Vedi', '[immagine]', 'sotto.'])
    expect(paragraphs[2]).toEqual([{ text: '[tabella]', index: null }])
  })
})

const FORMULAS = [
  ['z', 1, 0, false, 200],
  ['Ca^{2+}', 4, 0, false, 200],
  [String.raw`x_{\max}`, 2, 0, false, 200],
  [String.raw`\sum_{i=1}^{6} x_i`, 6, 1, true, 800],
  [String.raw`z = \frac{x - x_{\min}}{x_{\max} - x_{\min}}`, 11, 1, true, 1050],
] as const
const formula = (tex: string): Word => ({ text: tex, para: 0, math: { html: '<math/>', tex, complex: formulaMetrics(tex).complex } })
const formulaPrefs = { wpm: 300, pauseMs: 400, comma: false, formulaPause: 'adattiva', formulaMs: 2000 } as const

it.each(FORMULAS)('classificazione e durata della tabella: %s', (tex, atoms, structures, complex, ms) => {
  expect(formulaMetrics(tex)).toEqual({ atoms, structures, complex })
  expect(wordDelay(formula(tex), formulaPrefs)).toBe(ms)
  expect(graveWord(formula(tex), formulaPrefs)).toBe(complex)
  expect(wordDelay(formula(tex), { ...formulaPrefs, formulaPause: 'standard' })).toBe(200)
  expect(graveWord(formula(tex), { ...formulaPrefs, formulaPause: 'standard' })).toBe(false)
  expect(wordDelay(formula(tex), { ...formulaPrefs, formulaPause: 'personalizzata' })).toBe(complex ? 2000 : 200)
})
it('conta ambienti e formattazione, e aggiunge la pausa dopo la formula', () => {
  expect(formulaMetrics(String.raw`\begin{matrix}a&b\end{matrix}`)).toEqual({ atoms: 3, structures: 1, complex: true })
  expect(formulaMetrics(String.raw`\mathrm{Ca}\,^{2+}`)).toEqual({ atoms: 4, structures: 0, complex: false })
  expect(wordDelay({ ...formula(String.raw`\sqrt{x}`), text: 'formula.' }, formulaPrefs)).toBe(950)
})
it('legge una formula in linea e una a blocco, clona l’HTML e associa la punteggiatura', () => {
  const root = document.createElement('div')
  root.innerHTML = '<p>Leggi <span class="katex"><span>Ca</span><annotation encoding="application/x-tex">Ca^{2+}</annotation></span>.</p>'
    + '<div class="katex-display"><span class="katex"><annotation encoding="application/x-tex">\\sqrt{x}</annotation></span></div>'
    + '<p><math display="block"><semantics><mi>z</mi><annotation encoding="application/x-tex">z</annotation></semantics></math></p>'
  const result = readUnitWords(root)
  const math = result.words.filter(w => w.math)
  expect(math).toHaveLength(3)
  expect(math[0]).toMatchObject({ text: 'Ca^{2+}.', math: { tex: 'Ca^{2+}', complex: false } })
  expect(math[1].math?.complex).toBe(true)
  expect(math[2].math?.complex).toBe(false)
  expect(math[0].math?.html).toContain('class="katex"')
  expect(result.paragraphs.flat().filter(p => p.math)).toHaveLength(3)
  expect(result.paragraphs.flat().map(p => p.text)).not.toContain('[formula]')
})
