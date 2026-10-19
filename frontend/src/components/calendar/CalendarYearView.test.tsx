import { fireEvent, render, screen } from '@testing-library/react'
import { CalendarYearView } from './CalendarYearView'

it('seleziona una settimana e Invio o doppio clic la apre, senza leggende', () => {
  const onSelect = vi.fn(), onOpen = vi.fn()
  const weeks = [{ start_date: '2026-10-19', week_number: 43, days: [{ date: '2026-10-19', status: '', events: [{ start_hour: 9, end_hour: 11, materia: 'Bio', status: 'nonseguita', is_recorded: false }] }] }]
  render(<CalendarYearView weeks={weeks} selected={['2026-10-19']} onSelect={onSelect} onOpen={onOpen} />)
  const row = screen.getByRole('button', { name: /Settimana 43/ })
  expect(row).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(row)
  expect(onSelect).toHaveBeenCalledWith('2026-10-19')
  fireEvent.keyDown(row, { key: 'Enter' })
  fireEvent.doubleClick(row)
  expect(onOpen).toHaveBeenCalledTimes(2)
  expect(screen.queryByText('2 ore')).not.toBeInTheDocument()
})
