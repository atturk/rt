import { clampRate, formatRate, loadRate, saveRate } from './playbackRate'

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
  data.set('rt-playback-rate', 'boh')
  expect(loadRate(storage)).toBe(1)
  const broken = { getItem: () => { throw new Error('no') }, setItem: () => { throw new Error('no') } }
  expect(loadRate(broken)).toBe(1)
  expect(() => saveRate(2, broken)).not.toThrow()
})
