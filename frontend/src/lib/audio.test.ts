import { activeUnit, formatTime, neighbourStart } from './audio'

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
