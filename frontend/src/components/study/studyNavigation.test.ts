import { studyNavigation } from './studyNavigation'

it('cambia unità in mezzo e mostra l’effetto ai due estremi', () => {
  expect(studyNavigation(-1, 0, 3, 0, 1)).toBe('left-edge')
  expect(studyNavigation(1, 2, 3, 0, 1)).toBe('right-edge')
  expect(studyNavigation(-1, 1, 3, 0, 1)).toBe('previous-unit')
  expect(studyNavigation(1, 1, 3, 0, 1)).toBe('next-unit')
})
it('attraversa le lezioni e riserva l’effetto agli estremi della sequenza', () => {
  expect(studyNavigation(1, 2, 3, 0, 2)).toBe('next-lesson')
  expect(studyNavigation(-1, 0, 3, 1, 2)).toBe('previous-lesson')
  expect(studyNavigation(1, 2, 3, 1, 2)).toBe('right-edge')
  expect(studyNavigation(-1, 0, 3, 0, 2)).toBe('left-edge')
})
