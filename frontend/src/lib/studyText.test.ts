import { afterEach, expect, it } from 'vitest'

import { clampStudyTextScale, getSavedStudyTextScale, saveStudyTextScale, STUDY_FONT_DEFAULT, STUDY_TEXT_SCALE_KEY, studyFontStack } from './studyText'

afterEach(() => localStorage.clear())

it('il font predefinito è sistema', () => {
  expect(STUDY_FONT_DEFAULT).toBe('sistema')
  expect(studyFontStack('sistema')).toBe('var(--font-sans)')
  expect(studyFontStack('sconosciuto')).toBe('var(--font-sans)')
})

it('lo stack di seravek contiene Seravek', () => {
  expect(studyFontStack('seravek')).toContain('Seravek')
})

it('la scala resta fra 0,8 e 2,0 a passi di 0,1', () => {
  expect(clampStudyTextScale(0.5)).toBe(0.8)
  expect(clampStudyTextScale(3)).toBe(2)
  expect(clampStudyTextScale(1.23)).toBe(1.2)
  expect(clampStudyTextScale(Number.NaN)).toBe(1)
  saveStudyTextScale(5)
  expect(localStorage.getItem(STUDY_TEXT_SCALE_KEY)).toBe('2.0')
  expect(getSavedStudyTextScale()).toBe(2)
})
