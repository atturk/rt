import { pricingToRows, rowsToPricing } from './settings'

describe('pricing', () => {
  it('andata e ritorno con la virgola decimale e il reasoning facoltativo', () => {
    const pricing = { openrouter: { 'a/b': { input_per_million: 0.15, output_per_million: 0.6 } } }
    const rows = pricingToRows(pricing)
    expect(rows).toEqual([{ provider: 'openrouter', model: 'a/b', input: '0.15', output: '0.6', reasoning: '' }])
    expect(rowsToPricing([...rows, { provider: 'deepseek', model: 'x', input: '1,5', output: '2', reasoning: '3' }])).toEqual({
      ...pricing,
      deepseek: { x: { input_per_million: 1.5, output_per_million: 2, reasoning_per_million: 3 } },
    })
  })
  it('righe vuote ignorate, prezzi non validi rifiutati', () => {
    expect(rowsToPricing([{ provider: '', model: '', input: '', output: '', reasoning: '' }])).toEqual({})
    expect(() => rowsToPricing([{ provider: 'p', model: 'm', input: '-1', output: '1', reasoning: '' }])).toThrow('inserisci un prezzo')
    expect(() => rowsToPricing([{ provider: '', model: 'm', input: '1', output: '1', reasoning: '' }])).toThrow('provider e modello')
  })
})
