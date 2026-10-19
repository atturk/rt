import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'
import type { CalendarDayView, CalendarEventView } from '@/api/calendar'
import { CalendarWeekGrid } from './CalendarWeekGrid'
import { CalendarDayList } from './CalendarDayList'
import { EventTooltipContent } from './EventTooltipContent'
import { getEventTooltip } from './calendarUtils'

const event: CalendarEventView = {
  key: 'tpl_1', date: '2026-10-19', day_of_week: 0,
  start_time: '09:30', end_time: '11:30', start_hour: 9.5, end_hour: 11.5,
  materia: 'Analisi', docente: 'Prof. Rossi', status: 'seguire', is_modified: true,
  is_recorded: false, note: 'Aula 2\nPortare gli appunti',
}
const day: CalendarDayView = { date: event.date, day_of_week: 0, day_name: 'Lun', day_number: 19, month_name: 'ottobre', status: '', is_today: false, events: [event] }
let now = Date.parse('2030-01-01')
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(now += 10000)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('ordina le righe conservando il testo accessibile', () => {
  const { container } = render(<EventTooltipContent event={event} editing />)
  expect(screen.getByText("Modifica quest'ora")).toBeVisible()
  expect(screen.getByText('Analisi')).toHaveClass('font-semibold')
  expect(screen.getByText('09:30–11:30')).toHaveClass('font-mono')
  expect(container).toHaveTextContent('Prof. Rossi')
  expect(container).toHaveTextContent('Da seguireSolo questa settimana')
  expect(screen.getByText(/Aula 2/)).toHaveClass('whitespace-pre-line', 'line-clamp-4', 'border-t')
  expect(getEventTooltip(event)).toBe('Analisi · 09:30–11:30 · Prof. Rossi\nDa seguire\nSolo questa settimana\nNota: Aula 2\nPortare gli appunti')
})
it.each(['griglia', 'giorno'])('%s: nota immediata, un solo suggerimento e clic sul dettaglio', view => {
  const onOpen = vi.fn()
  if (view === 'griglia') render(<CalendarWeekGrid days={[day]} editing={null} selectedEventKey={null} onOpenEvent={onOpen} onOpenDayMenu={vi.fn()} onOpenAdd={vi.fn()} onRemoveEvent={vi.fn()} />)
  else render(<CalendarDayList days={[day]} selectedDayIndex={0} onSelectDayIndex={vi.fn()} onOpenEvent={onOpen} />)
  const block = screen.getByTestId(`calendar-${view === 'griglia' ? 'event' : 'mobile-event'}-tpl_1`)
  const note = within(block).getByTestId('calendar-note-tpl_1')
  expect(block.querySelector('button')).toBeNull()
  expect(block).toHaveAccessibleName(/Nota: Aula 2/)
  expect(note.querySelector('.size-1')).toBeTruthy()
  fireEvent.mouseEnter(block); act(() => vi.advanceTimersByTime(100)); fireEvent.mouseEnter(note)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Aula 2')
  expect(screen.getByRole('tooltip')).not.toHaveTextContent('Prof. Rossi')
  expect(screen.getByRole('tooltip').firstChild).toHaveClass('line-clamp-6')
  act(() => vi.advanceTimersByTime(1000))
  expect(screen.getAllByRole('tooltip')).toHaveLength(1)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Portare gli appunti')
  fireEvent.mouseLeave(note)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  fireEvent.mouseEnter(note); fireEvent.pointerDown(note)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  fireEvent.click(note)
  expect(onOpen).toHaveBeenCalledWith(event, expect.any(Object))
})
it('non aggiunge il segnale né il suggerimento per una nota vuota', () => {
  render(<CalendarDayList days={[{ ...day, events: [{ ...event, note: '  ' }] }]} selectedDayIndex={0} onSelectDayIndex={vi.fn()} onOpenEvent={vi.fn()} />)
  expect(screen.queryByTestId('calendar-note-tpl_1')).not.toBeInTheDocument()
})
it.each(['seguire', 'seguita', 'nonseguita', 'saltare', 'annullata'])('mantiene lo stato %s del suggerimento precedente', status => {
  const value = { ...event, status, is_modified: false, note: null } as CalendarEventView
  const { container } = render(<EventTooltipContent event={value} />)
  expect(container).toHaveTextContent(getEventTooltip(value).split('\n')[1])
})
it.each([0, 8])('mostra il progresso della lezione con %i unità', total => {
  const value = { ...event, lesson: { id: 1, path: '/lezione', titolo: 'Lezione', materia: 'Analisi', data: event.date, ora: '09:30', units_total: total, units_learned: 5, is_processing: false } }
  render(<EventTooltipContent event={value} />)
  expect(screen.getByText(total ? 'Seguita · 5/8 unità apprese' : 'Seguita · in rielaborazione', { exact: false })).toBeVisible()
})
