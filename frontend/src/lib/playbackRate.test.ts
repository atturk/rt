import { clampRate, formatRate, formatSpeed, loadRate, nextSpeed, saveRate } from './playbackRate'

it('limita la velocità tra 0.5× e 3× a passi di 0.05', () => {
  expect(clampRate(0.1)).toBe(0.5)
  expect(clampRate(7)).toBe(3)
  expect(clampRate(1.2500000000000002)).toBe(1.25)
  expect(clampRate(1.37)).toBe(1.35)
  expect(clampRate(Number.NaN)).toBe(1)
  expect(formatRate(1.5)).toBe('1.5×')
})

it('salva e rilegge la preferenza, 1× se manca o non è valida', () => {
  const data = new Map<string, string>()
  const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) }
  expect(loadRate(storage)).toBe(1)
  saveRate(1.75, storage)
  expect(loadRate(storage)).toBe(1.75)
  data.set('rt-pref:audio.rate', 'boh')
  expect(loadRate(storage)).toBe(1)
  const broken = { getItem: () => { throw new Error('no') }, setItem: () => { throw new Error('no') } }
  expect(loadRate(broken)).toBe(1)
  expect(() => saveRate(2, broken)).not.toThrow()
})

it('il pulsante velocità gira fra 1× · 1,25× · 1,5× · 1,75× · 2× e poi torna a 1×', () => {
  const seen: string[] = []
  let rate = 1
  for (let i = 0; i < 6; i++) {
    seen.push(formatSpeed(rate))
    rate = nextSpeed(rate)
  }
  expect(seen).toEqual(['1×', '1,25×', '1,5×', '1,75×', '2×', '1×'])
  // Valori del vecchio slider: si va al primo valore fisso sopra.
  expect(nextSpeed(1.15)).toBe(1.25)
  expect(nextSpeed(2.5)).toBe(1)
  expect(nextSpeed(0.5)).toBe(1)
})
