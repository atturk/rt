import { fitPopup } from './studyNoteWindow'

it('contiene citazioni e risposte alte, anche quando la finestra si restringe', () => {
  const frame = fitPopup({ x: 950, y: 700, width: 440, height: null }, { width: 1024, height: 768 }, 650)
  expect(frame.x).toBeGreaterThanOrEqual(12)
  expect(frame.x + frame.width).toBeLessThanOrEqual(1012)
  expect(frame.y + 650).toBeLessThanOrEqual(756)
  const small = fitPopup({ ...frame, width: 900, height: 900 }, { width: 390, height: 400 })
  expect(small.width).toBe(366)
  expect(small.height).toBe(376)
  expect(small.x).toBe(12)
  expect(small.y).toBe(12)
})

it('rispetta la misura minima e posiziona il pannello a destra a tutta altezza', () => {
  const small = fitPopup({ x: -100, y: -100, width: 20, height: 20 }, { width: 1000, height: 800 })
  expect(small).toMatchObject({ x: 12, y: 12, width: 320, height: 240 })
  expect(fitPopup({ x: 100, y: 200, width: 520, height: 300, docked: true }, { width: 1000, height: 800 }))
    .toMatchObject({ x: 480, y: 0, width: 520, height: 800 })
})
