import { describe, expect, it, beforeEach } from 'vitest'
import {
  clearLastClosedLessonId,
  consumeLastClosedLessonId,
  getLastClosedLessonId,
  setLastClosedLessonId,
} from './lastClosedLesson'

describe('lastClosedLesson module', () => {
  beforeEach(() => {
    clearLastClosedLessonId()
  })

  it('starts null', () => {
    expect(getLastClosedLessonId()).toBeNull()
    expect(consumeLastClosedLessonId()).toBeNull()
  })

  it('saves and consumes lesson id once', () => {
    setLastClosedLessonId(42)
    expect(getLastClosedLessonId()).toBe(42)
    expect(consumeLastClosedLessonId()).toBe(42)
    expect(getLastClosedLessonId()).toBeNull()
    expect(consumeLastClosedLessonId()).toBeNull()
  })

  it('can be cleared manually', () => {
    setLastClosedLessonId(15)
    clearLastClosedLessonId()
    expect(getLastClosedLessonId()).toBeNull()
    expect(consumeLastClosedLessonId()).toBeNull()
  })
})
