import { expect, it } from 'vitest'
import { placeTooltip } from './tooltipPlacement'

const viewport = { width: 1000, height: 700 }
const rect = (left: number, top: number, width = 40, height = 32) => ({ left, top, width, height, right: left + width, bottom: top + height })
const bubble = { width: 200, height: 30 }

it('sopra quando c’è posto, centrato sul controllo', () => {
  expect(placeTooltip(rect(400, 300), bubble, 'top', viewport)).toEqual({ top: 300 - 8 - 30, left: 420 - 100 })
})
it('in cima alla finestra passa sotto (gomma ed evidenziatore dello Studio)', () => {
  expect(placeTooltip(rect(400, 10), bubble, 'top', viewport)).toEqual({ top: 10 + 32 + 8, left: 320 })
})
it('in fondo alla finestra passa sopra', () => {
  expect(placeTooltip(rect(400, 660), bubble, 'bottom', viewport).top).toBe(660 - 8 - 30)
})
it('resta dentro la finestra a destra e a sinistra', () => {
  expect(placeTooltip(rect(950, 300), bubble, 'bottom', viewport).left).toBe(1000 - 8 - 200)
  expect(placeTooltip(rect(0, 300), bubble, 'top', viewport).left).toBe(8)
})
it('a destra passa a sinistra se non ci sta, e resta in verticale nella finestra', () => {
  expect(placeTooltip(rect(900, 2), bubble, 'right', viewport)).toEqual({ top: 8, left: 900 - 8 - 200 })
  expect(placeTooltip(rect(60, 300), bubble, 'right', viewport).left).toBe(108)
})
