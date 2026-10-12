import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { getSubjectColor } from './subjectColor'
import { StatusIcon } from './StatusIcon'
import { CalendarWeekGrid } from './CalendarWeekGrid'
import { CalendarDayList } from './CalendarDayList'
import { DayMenuPopup, WeekInfoPopup } from './CalendarPopups'
import type { CalendarDayView, CalendarEventView, CalendarWeekSummary } from '@/api/calendar'

const dummyEvent: CalendarEventView = {
  key: 'tpl_1',
  date: '2026-10-12',
  day_of_week: 0,
  start_time: '09:30',
  end_time: '11:30',
  start_hour: 9.5,
  end_hour: 11.5,
  materia: 'Data Mining',
  docente: 'Prof. Ferraris',
  status: 'seguita',
  is_modified: false,
  is_recorded: true,
  lesson: {
    id: 1,
    path: '/path/lesson',
    titolo: 'Clustering gerarchico',
    materia: 'Data Mining',
    data: '2026-10-12',
    ora: '09:30',
    units_learned: 5,
    units_total: 8,
    is_processing: false,
  },
}

const dummyDay: CalendarDayView = {
  date: '2026-10-12',
  day_of_week: 0,
  day_name: 'Lun',
  day_number: 12,
  month_name: 'ottobre',
  status: '',
  is_today: true,
  events: [dummyEvent],
}

describe('Calendar components (CA1c)', () => {
  it('getSubjectColor assigns consistent color based on subject name', () => {
    const c1 = getSubjectColor('Data Mining')
    const c2 = getSubjectColor('Data Mining')
    expect(c1).toBe(c2)
    expect(c1.startsWith('var(--m')).toBe(true)
  })

  it('StatusIcon renders progress ring when lesson has units', () => {
    const { container } = render(<StatusIcon event={dummyEvent} />)
    expect(container.querySelector('svg.size-\\[15px\\]')).toBeTruthy()
  })

  it('StatusIcon renders checkmark for seguita without lesson', () => {
    const eventWithoutLesson: CalendarEventView = {
      ...dummyEvent,
      lesson: null,
      status: 'seguita',
    }
    const { container } = render(<StatusIcon event={eventWithoutLesson} />)
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('CalendarWeekGrid renders day headers and events', () => {
    const onOpenEvent = vi.fn()
    const onOpenDayMenu = vi.fn()
    const onOpenAdd = vi.fn()
    const onRemoveEvent = vi.fn()

    render(
      <MemoryRouter>
        <CalendarWeekGrid
          days={[dummyDay]}
          editing={null}
          selectedEventKey={null}
          onOpenEvent={onOpenEvent}
          onOpenDayMenu={onOpenDayMenu}
          onOpenAdd={onOpenAdd}
          onRemoveEvent={onRemoveEvent}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Lun')).toBeTruthy()
    expect(screen.getByText('DATA MINING')).toBeTruthy()
    expect(screen.getByText('09:30–11:30')).toBeTruthy()

    // Clic sull'evento apre il popup
    const evBtn = screen.getByRole('button', { name: /DATA MINING/i })
    fireEvent.click(evBtn)
    expect(onOpenEvent).toHaveBeenCalledWith(dummyEvent, expect.any(Object))
  })

  it('CalendarDayList renders mobile day strip and events', () => {
    const onSelectDay = vi.fn()
    const onOpenEvent = vi.fn()

    render(
      <MemoryRouter>
        <CalendarDayList
          days={[dummyDay]}
          selectedDayIndex={0}
          onSelectDayIndex={onSelectDay}
          onOpenEvent={onOpenEvent}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Lun')).toBeTruthy()
    expect(screen.getByText('DATA MINING')).toBeTruthy()
    expect(screen.getByText('Prof. Ferraris')).toBeTruthy()
  })

  it('DayMenuPopup renders whole day options and triggers change', () => {
    const onClose = vi.fn()
    const onSetDayState = vi.fn()

    render(
      <DayMenuPopup
        day={dummyDay}
        anchor={{ x: 100, y: 100, width: 50, height: 20 }}
        onClose={onClose}
        onSetDayState={onSetDayState}
      />,
    )

    const skipBtn = screen.getByRole('button', { name: /Da saltare/i })
    fireEvent.click(skipBtn)
    expect(onSetDayState).toHaveBeenCalledWith('saltare')
    expect(onClose).toHaveBeenCalled()
  })

  it('WeekInfoPopup renders summary information', () => {
    const onClose = vi.fn()
    const summary: CalendarWeekSummary = {
      hours_total: 10.0,
      recorded_count: 3,
      skip_count: 1,
      modified_hours_count: 2,
      to_recover: [
        {
          key: 'past_1',
          date: '2026-10-05',
          day_of_week: 0,
          day_name: 'Lun',
          day_number: 5,
          month_number: 10,
          materia: 'Generale',
          start_time: '14:00',
          end_time: '16:00',
        },
      ],
    }

    render(
      <WeekInfoPopup
        weekLabel="12–16 ottobre"
        weekNumber="41"
        summary={summary}
        anchor={{ x: 100, y: 100, width: 50, height: 20 }}
        onClose={onClose}
      />,
    )

    expect(screen.getByText('10')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('2 ore diverse')).toBeTruthy()
    expect(screen.getByText('Generale')).toBeTruthy()
    expect(screen.getByText('Lun 5/10')).toBeTruthy()
  })
})
