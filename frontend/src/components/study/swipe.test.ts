import { describe, expect, it } from 'vitest'
import { detectSwipe, isElementScrollableX, type SwipePoints } from './swipe'

describe('detectSwipe pure function', () => {
  const basePoints: SwipePoints = {
    startX: 150,
    startY: 200,
    startTime: 1000,
    endX: 50,
    endY: 205,
    endTime: 1300, // 300ms duration, dx = -100, dy = 5
  }

  it('riconosce swipe destra -> sinistra come next', () => {
    const result = detectSwipe(basePoints)
    expect(result).toBe('next')
  })

  it('riconosce swipe sinistra -> destra come prev', () => {
    const result = detectSwipe({
      ...basePoints,
      startX: 50,
      endX: 150, // dx = +100
    })
    expect(result).toBe('prev')
  })

  it('ignora se la distanza orizzontale è inferiore a 60 px', () => {
    const result = detectSwipe({
      ...basePoints,
      startX: 150,
      endX: 100, // dx = -50 (|dx| < 60)
    })
    expect(result).toBeNull()
  })

  it('ignora se la componente verticale è troppo grande (|dx| <= 2 * |dy|)', () => {
    const result = detectSwipe({
      ...basePoints,
      startX: 150,
      endX: 70, // dx = -80
      startY: 100,
      endY: 150, // dy = 50, 2 * |dy| = 100 > 80
    })
    expect(result).toBeNull()
  })

  it('ignora se il gesto dura più di 600 ms', () => {
    const result = detectSwipe({
      ...basePoints,
      endTime: 1700, // 700 ms
    })
    expect(result).toBeNull()
  })

  it('ignora se il tocco inizia nei primi 25 px da sinistra (iOS Safari back)', () => {
    const result = detectSwipe({
      ...basePoints,
      startX: 20,
    })
    expect(result).toBeNull()
  })

  it('ignora se c’è una selezione di testo in corso', () => {
    const result = detectSwipe(basePoints, { hasSelection: true })
    expect(result).toBeNull()
  })

  it('ignora se parte dentro un elemento che scorre in orizzontale', () => {
    const result = detectSwipe(basePoints, { inScrollable: true })
    expect(result).toBeNull()
  })
})

describe('isElementScrollableX', () => {
  it('identifica elementi con overflow orizzontale', () => {
    const container = document.createElement('div')
    const pre = document.createElement('pre')
    Object.defineProperty(pre, 'scrollWidth', { value: 500, configurable: true })
    Object.defineProperty(pre, 'clientWidth', { value: 300, configurable: true })
    container.appendChild(pre)

    expect(isElementScrollableX(pre, container)).toBe(true)
  })

  it('non marca come scrollabili elementi normali', () => {
    const container = document.createElement('div')
    const p = document.createElement('p')
    container.appendChild(p)

    expect(isElementScrollableX(p, container)).toBe(false)
  })
})
