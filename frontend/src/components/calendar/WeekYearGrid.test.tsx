import { fireEvent, render, screen, within } from '@testing-library/react'
import { WeekYearGrid } from './WeekYearGrid'

it('raggruppa per giovedì, distingue passato e oggi e naviga con le frecce', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-19T12:00:00'))
  const onSelect = vi.fn()
  const { container } = render(<WeekYearGrid currentDate="2026-10-19" entries={[
    { id: 1, materia: 'Test', day_of_week: 0, start_time: '09:00', end_time: '11:00', valid_from: '2026-10-12', valid_to: '2026-10-26' },
  ]} onSelect={onSelect} />)
  const week = (value: string) => container.querySelector<HTMLButtonElement>(`[data-week="${value}"]`)!
  expect(week('2026-08-31').closest('[data-month]')).toHaveAttribute('data-month', '2026-09')
  expect(week('2026-09-28').closest('[data-month]')).toHaveAttribute('data-month', '2026-10')
  expect(week('2026-10-12')).toHaveAttribute('data-past', 'true')
  expect(week('2026-10-19')).toHaveAttribute('data-current', 'true')
  expect(within(week('2026-10-19')).getByText('oggi')).toBeInTheDocument()
  expect(week('2026-10-12')).toHaveAttribute('data-changed', 'true')
  expect(screen.queryByText(/vuota · con ore/)).not.toBeInTheDocument()
  week('2026-10-19').focus()
  fireEvent.keyDown(week('2026-10-19'), { key: 'ArrowRight' })
  expect(week('2026-10-26')).toHaveFocus()
  fireEvent.click(week('2026-10-26'))
  expect(onSelect).toHaveBeenCalledWith('2026-10-26')
  vi.useRealTimers()
})
