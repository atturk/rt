import { act, fireEvent, render, screen } from '@testing-library/react'
import { StudyNotePopup } from './StudyNotePopup'
import { sheetHeights } from './studyNoteSheet'
import type { StudyNote } from '@/api/studyNotes'

afterEach(() => vi.unstubAllGlobals())

it('a 390 px parte a metà e mantiene il campo sopra la tastiera nel visualViewport', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  const visual = Object.assign(new EventTarget(), { width: 390, height: 844, offsetTop: 0, offsetLeft: 0 })
  vi.stubGlobal('visualViewport', visual)
  const { unmount } = render(<StudyNotePopup open kind="chiedi" unitId="1.1" quote="Un passaggio" onClose={vi.fn()} />)
  const popup = screen.getByRole('dialog')
  expect(popup.parentElement).toBe(document.body)
  expect(popup).toHaveAttribute('data-sheet-level', '1')
  expect(popup).toHaveClass('z-[55]')
  visual.height = 380
  visual.offsetTop = 30
  act(() => { visual.dispatchEvent(new Event('resize')) })
  expect(Number.parseFloat(popup.style.top) + Number.parseFloat(popup.style.height)).toBe(410)
  expect(screen.getByTestId('study-note-submit')).toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowUp' })
  expect(popup).toHaveAttribute('data-sheet-level', '2')
  fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowDown' })
  fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowDown' })
  expect(popup).toHaveAttribute('data-sheet-level', '0')
  unmount()
})

it('una risposta lunga porta il foglio a piena altezza', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  const note = { id: 1, lesson_id: 1, kind: 'chiedi', unit_id: '1.1', response: { spiegazione: 'Spiegazione lunga. '.repeat(100) } } as StudyNote
  const view = render(<StudyNotePopup open kind="chiedi" unitId="1.1" quote="Citazione" onClose={vi.fn()} />)
  view.rerender(<StudyNotePopup open kind="chiedi" unitId="1.1" quote="Citazione" onClose={vi.fn()} note={note} />)
  expect(screen.getByRole('dialog')).toHaveAttribute('data-sheet-level', '2')
})

it('le tre altezze lasciano spazio al fondo anche con la tastiera', () => {
  const heights = sheetHeights(380)
  expect(heights[0]).toBeGreaterThanOrEqual(200)
  expect(heights[0]).toBeLessThan(heights[1])
  expect(heights[1]).toBeLessThan(heights[2])
  expect(heights[2]).toBe(368)
})
