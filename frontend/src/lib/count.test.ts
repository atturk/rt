import { normalizeCountInput, parseCount } from './count'

describe('campo Immagini per unità', () => {
  it('toglie gli zeri iniziali mentre si digita e lascia svuotare il campo', () => {
    expect(normalizeCountInput('03')).toBe('3')
    expect(normalizeCountInput('007')).toBe('7')
    expect(normalizeCountInput('0')).toBe('0')
    expect(normalizeCountInput('00')).toBe('0')
    expect(normalizeCountInput('')).toBe('')
    expect(normalizeCountInput('10')).toBe('10')
  })

  it('valida al salvataggio: vuoto vale 0, fuori intervallo o non numerico è un errore', () => {
    expect(parseCount('')).toEqual({ ok: true, value: 0 })
    expect(parseCount('3')).toEqual({ ok: true, value: 3 })
    expect(parseCount('10')).toEqual({ ok: true, value: 10 })
    expect(parseCount('11')).toEqual({ ok: false, error: 'Scrivi un numero da 0 a 10.' })
    expect(parseCount('-1').ok).toBe(false)
    expect(parseCount('2.5').ok).toBe(false)
    expect(parseCount('tre').ok).toBe(false)
  })
})
