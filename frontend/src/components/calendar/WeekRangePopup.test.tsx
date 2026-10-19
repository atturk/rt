import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { WeekRangePopup } from './WeekRangePopup'

const anchor = { x: 100, y: 100, width: 20, height: 20 }
const entries = [{ id: 1, day_of_week: 0, start_time: '09:00', end_time: '11:00', materia: 'Analisi', valid_from: '2026-10-12', valid_to: '2026-10-26' }]
function open(onConfirm = vi.fn(), onClose = vi.fn()) {
  const result = render(<WeekRangePopup anchor={anchor} currentDate="2026-10-19" entries={entries} onConfirm={onConfirm} onClose={onClose} />)
  const week = (date: string) => result.container.querySelector<HTMLButtonElement>(`[data-week="${date}"]`)!
  return { ...result, week, onConfirm, onClose }
}
it('mostra occupazione e cambi di versione, con 53 settimane nel 2026', () => {
  const { week, container } = open()
  expect(container.querySelectorAll('[data-week]')).toHaveLength(53)
  expect(week('2026-10-12')).toHaveClass('occupata')
  expect(week('2026-10-05')).not.toHaveClass('occupata')
  expect(week('2026-10-12')).toHaveAttribute('data-changed', 'true')
  expect(week('2026-10-19')).toHaveAttribute('data-changed', 'false')
  expect(week('2026-10-26')).toHaveAttribute('data-changed', 'true')
  expect(week('2026-10-12')).toHaveAccessibleName(/2 ore/)
})
it('si ferma al 2025 e al 2035', () => {
  open()
  fireEvent.click(screen.getByRole('button', { name: 'Anno precedente' }))
  expect(screen.getByTestId('calendar-range-year')).toHaveTextContent('2025')
  expect(screen.getByRole('button', { name: 'Anno precedente' })).toBeDisabled()
  for (let i = 0; i < 10; i++) fireEvent.click(screen.getByRole('button', { name: 'Anno successivo' }))
  expect(screen.getByTestId('calendar-range-year')).toHaveTextContent('2035')
  expect(screen.getByRole('button', { name: 'Anno successivo' })).toBeDisabled()
})
it.each([false, true])('seleziona le settimane anche in ordine inverso: %s', reverse => {
  const { week, onConfirm } = open()
  const confirm = screen.getByRole('button', { name: 'Modifica queste settimane' })
  expect(confirm).toBeDisabled()
  fireEvent.click(week(reverse ? '2026-10-19' : '2026-10-12'))
  expect(confirm).toBeDisabled()
  fireEvent.click(week(reverse ? '2026-10-12' : '2026-10-19'))
  expect(week('2026-10-12')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(confirm)
  expect(onConfirm).toHaveBeenCalledWith({ from: '2026-10-12', to: '2026-10-26' })
})
it('conserva il primo clic passando a un altro anno', () => {
  const { week, onConfirm } = open()
  fireEvent.click(week('2026-12-28'))
  fireEvent.click(screen.getByRole('button', { name: 'Anno successivo' }))
  fireEvent.click(week('2027-01-04'))
  fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  expect(onConfirm).toHaveBeenCalledWith({ from: '2026-12-28', to: '2027-01-11' })
})
it('Esc e clic fuori chiudono il popup', () => {
  const { onClose } = open()
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
  fireEvent.pointerDown(document.body)
  expect(onClose).toHaveBeenCalledTimes(2)
})
it('Esc chiude il popup anche quando è aperto il suggerimento di una settimana', async () => {
  const { week, onClose } = open()
  fireEvent.mouseEnter(week('2026-10-12'))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('2 ore')
  fireEvent.keyDown(week('2026-10-12'), { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
})
