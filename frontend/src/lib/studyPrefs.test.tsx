import { renderHook } from '@testing-library/react'
import { vi } from 'vitest'
import { RSVP_DEFAULT, useRsvpPrefs } from './studyPrefs'

const preference = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('./preferences', () => ({ usePreference: () => [preference.value, vi.fn()] }))

it('Legno è il predefinito anche per preferenze salvate senza clickSound', () => {
  expect(RSVP_DEFAULT.clickSound).toBe('legno')
  preference.value = { sound: false, wpm: 500 }
  const { result, rerender } = renderHook(useRsvpPrefs)
  expect(result.current[0]).toMatchObject({ sound: false, wpm: 500, clickSound: 'legno', formulaPause: 'adattiva', formulaMs: 2000, highlights: true, slowHighlights: false })
  preference.value = { sound: true, clickSound: 'classico' }; rerender()
  expect(result.current[0].clickSound).toBe('classico')
})
