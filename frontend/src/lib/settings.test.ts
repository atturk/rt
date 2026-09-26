import { parseTopicLink, pricingToRows, rowsToPricing, rowsToTopics, topicsToRows } from './settings'

describe('parseTopicLink', () => {
  it('ricava chat (con -100) e topic dal link di un messaggio', () => {
    expect(parseTopicLink(' https://t.me/c/1234567890/12/34 ')).toEqual({ chatId: '-1001234567890', topicId: 12 })
  })
  it('rifiuta link che non sono di un topic', () => {
    expect(parseTopicLink('https://t.me/rtbot')).toBeNull()
  })
})

describe('topic per materia', () => {
  it('andata e ritorno, materia in maiuscolo, righe vuote ignorate', () => {
    const rows = topicsToRows({ FISIOLOGIA: 27, BIOCHIMICA: 12 })
    expect(rows[0]).toEqual({ materia: 'BIOCHIMICA', topic: '12' })
    expect(rowsToTopics([...rows, { materia: '', topic: '' }, { materia: 'anatomia', topic: ' 5 ' }])).toEqual({
      BIOCHIMICA: 12,
      FISIOLOGIA: 27,
      ANATOMIA: 5,
    })
  })
  it('errori leggibili', () => {
    expect(() => rowsToTopics([{ materia: 'X', topic: 'dodici' }])).toThrow('deve essere un numero')
    expect(() => rowsToTopics([{ materia: '', topic: '3' }])).toThrow('Manca la materia')
  })
})

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
