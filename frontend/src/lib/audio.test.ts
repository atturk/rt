import { activeUnit, formatTime, neighbourStart, unitSpeechProgress } from './audio'

const sections = [
  { unit_id: '1.1', start_seconds: 2 },
  { unit_id: '1.2', start_seconds: 70 },
  { unit_id: '2.1', start_seconds: 300 },
]

it('formatTime', () => {
  expect(formatTime(0)).toBe('0:00')
  expect(formatTime(65.4)).toBe('1:05')
  expect(formatTime(3725)).toBe('1:02:05')
})

it('activeUnit segue il tempo', () => {
  expect(activeUnit(sections, 0)).toBeNull()
  expect(activeUnit(sections, 2)).toBe('1.1')
  expect(activeUnit(sections, 100)).toBe('1.2')
  expect(activeUnit(sections, 5000)).toBe('2.1')
})

it('neighbourStart', () => {
  expect(neighbourStart(sections, 10, 1)).toBe(70)
  expect(neighbourStart(sections, 300, 1)).toBeNull()
  expect(neighbourStart(sections, 100, -1)).toBe(70)
  expect(neighbourStart(sections, 71, -1)).toBe(2)
})

describe('unitSpeechProgress', () => {
  const sec = {
    unit_id: '1.1',
    start_seconds: 0,
    end_seconds: 60,
    speech_segments: [
      [0, 40],
      [55, 60],
    ],
  }

  it('prima dell’unità ritorna 0%', () => {
    expect(unitSpeechProgress(sec, -1)).toEqual({ cur: false, done: false, percent: 0 })
  })

  it('dopo l’unità ritorna 100% e done', () => {
    expect(unitSpeechProgress(sec, 65)).toEqual({ cur: false, done: true, percent: 100 })
  })

  it('durante la pausa non avanza', () => {
    const at40 = unitSpeechProgress(sec, 40)
    const at45 = unitSpeechProgress(sec, 45)
    const at50 = unitSpeechProgress(sec, 50)
    expect(at40.cur).toBe(true)
    expect(at45.cur).toBe(true)
    expect(at50.cur).toBe(true)
    expect(at40.percent).toBeCloseTo((40 / 45) * 100)
    expect(at45.percent).toBe(at40.percent)
    expect(at50.percent).toBe(at40.percent)
  })

  it('avanza durante il parlato successivo', () => {
    const at57 = unitSpeechProgress(sec, 57)
    expect(at57.cur).toBe(true)
    expect(at57.percent).toBeCloseTo((42 / 45) * 100)
  })

  it('fallback lineare senza segmenti', () => {
    const linearSec = { unit_id: '2.1', start_seconds: 10, end_seconds: 30 }
    expect(unitSpeechProgress(linearSec, 20)).toEqual({ cur: true, done: false, percent: 50 })
  })
})

