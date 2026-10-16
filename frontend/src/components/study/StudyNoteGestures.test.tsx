import { fireEvent, render, screen } from '@testing-library/react'
import { StudyNotePopup } from './StudyNotePopup'

afterEach(() => vi.unstubAllGlobals())

it('trascina, ridimensiona e conserva la misura nella sessione restando nello schermo', () => {
  vi.stubGlobal('PointerEvent', MouseEvent)
  const popup = () => <StudyNotePopup open onClose={vi.fn()} kind="chiedi" unitId="1.1" quote="Una citazione" />
  const first = render(popup())
  fireEvent.doubleClick(screen.getByTestId('study-note-header'))
  fireEvent.pointerDown(screen.getByTestId('study-note-header'), { button: 0, clientX: 200, clientY: 100 })
  fireEvent.pointerMove(window, { clientX: -1000, clientY: -1000 })
  fireEvent.pointerUp(window)
  let dialog = screen.getByRole('dialog')
  expect(dialog).toHaveStyle({ left: '12px', top: '12px' })
  fireEvent.pointerDown(screen.getByTestId('study-note-resize-se'), { button: 0, clientX: 200, clientY: 100 })
  fireEvent.pointerMove(window, { clientX: 300, clientY: 200 })
  fireEvent.pointerUp(window)
  expect(dialog).toHaveStyle({ width: '540px', height: '340px' })
  first.unmount()
  render(popup())
  dialog = screen.getByRole('dialog')
  expect(dialog).toHaveStyle({ left: '12px', top: '12px', width: '540px', height: '340px' })
  vi.stubGlobal('innerWidth', 500)
  vi.stubGlobal('innerHeight', 300)
  fireEvent.resize(window)
  expect(dialog).toHaveStyle({ width: '476px', height: '276px' })
  fireEvent.doubleClick(screen.getByTestId('study-note-header'))
})
