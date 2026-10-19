import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { getSubjectColor } from './subjectColor'
import { StatusIcon } from './StatusIcon'
import { CalendarWeekGrid } from './CalendarWeekGrid'
import { CalendarDayList } from './CalendarDayList'
import { DayMenuPopup, WeekInfoPopup, EventPopup } from './CalendarPopups'
import { NewLessonContext } from '@/components/shell/newLesson'
import type {
  CalendarDayView,
  CalendarEventView,
  CalendarWeekSummary,
  CalendarWeekView,
} from '@/api/calendar'
import { CalendarPage } from '@/routes/calendar'

// La pagina legge la settimana e salva con le mutazioni: qui si sostituiscono con spie.
const calendarMocks = vi.hoisted(() => ({
  week: null as unknown,
  template: [] as unknown[],
  currentDate: undefined as string | undefined,
  createOverride: vi.fn(),
  deleteOverride: vi.fn(),
  createTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
}))

vi.mock('@/api/calendar', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/calendar')>()
  const mutation = (fn: (arg: unknown) => unknown) => ({
    mutate: (arg: unknown) => fn(arg),
    mutateAsync: async (arg: unknown) => fn(arg),
  })
  return {
    ...actual,
    useCalendarTemplate: () => ({ data: calendarMocks.template }),
    useCalendarWeek: (date?: string) => { calendarMocks.currentDate = date; return { data: calendarMocks.week, isPending: false, isError: false } },
    useCreateOverride: () => mutation(calendarMocks.createOverride),
    useDeleteOverride: () => mutation(calendarMocks.deleteOverride),
    useCreateTemplateEntry: () => mutation(calendarMocks.createTemplate),
    useDeleteTemplateEntry: () => mutation(calendarMocks.deleteTemplate),
    useSetDayState: () => mutation(vi.fn()),
    useSetEntryState: () => mutation(vi.fn()),
    useLinkLesson: () => mutation(vi.fn()),
  }
})

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return { ...actual, useLessons: () => ({ data: [] }) }
})

vi.mock('@/api/subjects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/subjects')>()
  return { ...actual, useSubjects: () => ({ data: [] }) }
})

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
    expect(within(screen.getByTestId('calendar-event-tpl_1')).getByText('09:30–11:30')).toBeVisible()

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
        weekStart="2026-10-12"
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

  it('CalendarWeekGrid mostra il docente sotto l\'orario solo se il blocco è abbastanza alto', () => {
    const shortEvent: CalendarEventView = {
      ...dummyEvent,
      key: 'tpl_2',
      start_time: '14:00',
      end_time: '15:00',
      start_hour: 14,
      end_hour: 15,
      docente: 'Prof. Breve',
    }
    render(
      <MemoryRouter>
        <CalendarWeekGrid
          days={[{ ...dummyDay, events: [dummyEvent, shortEvent] }]}
          editing={null}
          selectedEventKey={null}
          onOpenEvent={vi.fn()}
          onOpenDayMenu={vi.fn()}
          onOpenAdd={vi.fn()}
          onRemoveEvent={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('calendar-event-docente-tpl_1')).toHaveTextContent('Prof. Ferraris')
    // L'ora di un'ora sola non ha posto per la terza riga: il docente resta nel nome accessibile.
    expect(screen.queryByTestId('calendar-event-docente-tpl_2')).toBeNull()
    expect(screen.getByRole('button', { name: /Prof\. Breve/ })).toBeTruthy()
  })

  it('CalendarWeekGrid in modifica: il clic su un\'ora chiama onEditEvent, non onOpenEvent', () => {
    const onOpenEvent = vi.fn()
    const onEditEvent = vi.fn()
    render(
      <MemoryRouter>
        <CalendarWeekGrid
          days={[dummyDay]}
          editing="week"
          selectedEventKey={null}
          onOpenEvent={onOpenEvent}
          onOpenDayMenu={vi.fn()}
          onOpenAdd={vi.fn()}
          onRemoveEvent={vi.fn()}
          onEditEvent={onEditEvent}
        />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByTestId('calendar-event-tpl_1'))
    expect(onEditEvent).toHaveBeenCalledWith(dummyEvent, expect.any(Object))
    expect(onOpenEvent).not.toHaveBeenCalled()
  })
})

describe('CalendarPage: modifica di un\'ora', () => {
  const tplEvent: CalendarEventView = {
    ...dummyEvent,
    key: 'tpl_7',
    lesson: null,
    status: 'seguire',
    is_recorded: false,
    template_entry_id: 7,
    override_id: null,
  }
  const week = {
    start_date: '2026-10-12',
    end_date: '2026-10-16',
    week_number: '42',
    label: '12–16 ottobre',
    days: [{ ...dummyDay, events: [tplEvent] }],
    summary: {
      hours_total: 2,
      recorded_count: 0,
      skip_count: 0,
      modified_hours_count: 0,
      to_recover: [],
    },
  } as unknown as CalendarWeekView

  beforeEach(() => {
    calendarMocks.week = week
    for (const fn of [
      calendarMocks.createOverride,
      calendarMocks.deleteOverride,
      calendarMocks.createTemplate,
      calendarMocks.deleteTemplate,
    ]) {
      fn.mockReset()
      fn.mockResolvedValue({})
    }
  })

  function renderPage() {
    render(
      <MemoryRouter>
        <CalendarPage />
      </MemoryRouter>,
    )
  }

  function enterEditing(label: RegExp) {
    fireEvent.click(screen.getByRole('button', { name: label }))
  }

  function openEdit() {
    fireEvent.click(screen.getByTestId('calendar-event-tpl_7'))
    return screen.getByRole('dialog', { name: 'Modifica ora' })
  }

  it('senza modifica il clic apre il dettaglio dell\'ora', () => {
    renderPage()
    fireEvent.click(screen.getByTestId('calendar-event-tpl_7'))
    expect(screen.getByTestId('calendar-event-popup')).toBeTruthy()
    expect(screen.queryByRole('dialog', { name: 'Modifica ora' })).toBeNull()
  })

  it('in modifica il clic apre il popup precompilato', () => {
    renderPage()
    enterEditing(/^Modifica solo questa settimana$/)
    const popup = openEdit()
    expect(screen.getByDisplayValue('Data Mining')).toBeTruthy()
    expect(screen.getByDisplayValue('09:30')).toBeTruthy()
    expect(screen.getByDisplayValue('11:30')).toBeTruthy()
    expect(screen.getByDisplayValue('Prof. Ferraris')).toBeTruthy()
    expect(popup).toHaveTextContent(/Modifica ora/)
    expect(screen.getByRole('button', { name: 'Salva' })).toBeTruthy()
  })

  it('solo questa settimana: salva una modifica puntuale (modified) dell\'ora tipo', async () => {
    renderPage()
    enterEditing(/^Modifica solo questa settimana$/)
    openEdit()
    fireEvent.change(screen.getByDisplayValue('11:30'), { target: { value: '12:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() =>
      expect(calendarMocks.createOverride).toHaveBeenCalledWith({
        date: '2026-10-12',
        action: 'modified',
        template_entry_id: 7,
        start_time: '09:30',
        end_time: '12:00',
        materia: 'Data Mining',
        docente: 'Prof. Ferraris',
      }),
    )
    expect(calendarMocks.deleteOverride).not.toHaveBeenCalled()
    expect(calendarMocks.createTemplate).not.toHaveBeenCalled()
    expect(calendarMocks.deleteTemplate).not.toHaveBeenCalled()
  })

  it('solo questa settimana: una modifica già presente si sostituisce', async () => {
    calendarMocks.week = {
      ...week,
      days: [{ ...dummyDay, events: [{ ...tplEvent, override_id: 31, is_modified: true }] }],
    }
    renderPage()
    enterEditing(/^Modifica solo questa settimana$/)
    openEdit()
    fireEvent.change(screen.getByDisplayValue('Prof. Ferraris'), { target: { value: 'Prof. Rossi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() => expect(calendarMocks.deleteOverride).toHaveBeenCalledWith(31))
    expect(calendarMocks.createOverride).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'modified', template_entry_id: 7, docente: 'Prof. Rossi' }),
    )
  })

  it('settimana tipo: chiude l\'ora dal lunedì e la ricrea valida dal lunedì', async () => {
    renderPage()
    enterEditing(/^Modifica la settimana tipo, da questa settimana in poi$/)
    openEdit()
    fireEvent.change(screen.getByDisplayValue('09:30'), { target: { value: '10:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() =>
      expect(calendarMocks.deleteTemplate).toHaveBeenCalledWith({ id: 7, from: '2026-10-12' }),
    )
    expect(calendarMocks.createTemplate).toHaveBeenCalledWith({
      day_of_week: 0,
      start_time: '10:00',
      end_time: '11:30',
      materia: 'Data Mining',
      docente: 'Prof. Ferraris',
      valid_from: '2026-10-12',
    })
    expect(calendarMocks.createOverride).not.toHaveBeenCalled()
  })

  it('nasconde collega e importa per una ora annullata', () => {
    render(<EventPopup event={{ ...dummyEvent, lesson: null, is_recorded: false, status: 'annullata' }}
      anchor={{ x: 100, y: 100, width: 50, height: 30 }} onClose={vi.fn()}
      onStatusChange={vi.fn()} onNoteSave={vi.fn()} onLinkLesson={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Collega una lezione' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: "Importa una lezione per quest'ora" })).not.toBeInTheDocument()
  })

  it("UI1: popup ora non registrata mostra + per importare e apre NewLessonContext con date e slotKey", () => {
    const openNewLesson = vi.fn()
    const onClose = vi.fn()
    const unrecordedEvent: CalendarEventView = {
      ...dummyEvent,
      key: 'tpl_42',
      date: '2026-10-14',
      lesson: undefined,
      is_recorded: false,
    }
    render(
      <NewLessonContext value={openNewLesson}>
        <EventPopup
          event={unrecordedEvent}
          anchor={{ x: 100, y: 100, width: 50, height: 30 }}
          onClose={onClose}
          onStatusChange={vi.fn()}
          onNoteSave={vi.fn()}
          onLinkLesson={vi.fn()}
        />
      </NewLessonContext>,
    )
    const plusBtn = screen.getByRole('button', { name: "Importa una lezione per quest'ora" })
    expect(plusBtn).toBeInTheDocument()
    fireEvent.click(plusBtn)
    expect(onClose).toHaveBeenCalled()
    expect(openNewLesson).toHaveBeenCalledWith({ date: '2026-10-14', slotKey: 'tpl_42' })
  })
})

describe('CalendarPage: intervallo di settimane', () => {
  const event = { ...dummyEvent, lesson: null, template_entry_id: 7, key: 'tpl_7' }
  const week = {
    start_date: '2026-10-12', end_date: '2026-10-16', week_number: '42', label: '12–16 ottobre',
    days: [{ ...dummyDay, events: [event] }], summary: { hours_total: 2, recorded_count: 0, skip_count: 0, modified_hours_count: 0, to_recover: [] },
  }
  beforeEach(() => {
    calendarMocks.week = week
    calendarMocks.template = []
    for (const mock of [calendarMocks.createTemplate, calendarMocks.deleteTemplate, calendarMocks.createOverride, calendarMocks.deleteOverride]) mock.mockReset().mockResolvedValue({})
  })
  function renderPage() { render(<MemoryRouter><CalendarPage /></MemoryRouter>) }
  function chooseRange() {
    fireEvent.click(screen.getByRole('button', { name: 'Modifica la settimana tipo in un intervallo di settimane' }))
    // L'anno non dipende dal giorno in cui viene eseguita la suite.
    while (Number(screen.getByTestId('calendar-range-year').textContent) > 2026) fireEvent.click(screen.getByRole('button', { name: 'Anno precedente' }))
    while (Number(screen.getByTestId('calendar-range-year').textContent) < 2026) fireEvent.click(screen.getByRole('button', { name: 'Anno successivo' }))
    const popup = screen.getByTestId('calendar-range-popup')
    fireEvent.click(popup.querySelector('[data-week="2026-10-19"]')!)
    fireEvent.click(popup.querySelector('[data-week="2026-10-12"]')!)
    fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  }
  it('conferma il modo range, va alla prima settimana e aggiunge solo nelle date scelte', () => {
    renderPage(); chooseRange()
    expect(calendarMocks.currentDate).toBe('2026-10-12')
    expect(screen.getByRole('button', { name: 'Cambia intervallo di settimane' })).toHaveTextContent('Settimane 42–43')
    fireEvent.click(screen.getAllByRole('button', { name: 'Aggiungi alle 08:30' })[0])
    const popup = screen.getByRole('dialog', { name: 'Aggiungi ora' })
    expect(popup).toHaveTextContent('Settimane 42–43')
    fireEvent.change(within(popup).getByLabelText('Materia'), { target: { value: 'Fisica' } })
    fireEvent.click(within(popup).getByRole('button', { name: 'Aggiungi' }))
    expect(calendarMocks.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ materia: 'Fisica', valid_from: '2026-10-12', valid_to: '2026-10-26' }))
    expect(calendarMocks.createOverride).not.toHaveBeenCalled()
  })
  it('toglie l’ora solo nell’intervallo', () => {
    renderPage(); chooseRange()
    fireEvent.click(screen.getByRole('button', { name: "Togli quest'ora" }))
    expect(calendarMocks.deleteTemplate).toHaveBeenCalledWith({ id: 7, from: '2026-10-12', to: '2026-10-26' })
  })
  it('crea la modifica prima di togliere la vecchia ora, usando gli stessi limiti', async () => {
    renderPage(); chooseRange()
    fireEvent.click(screen.getByTestId('calendar-event-tpl_7'))
    const popup = screen.getByRole('dialog', { name: 'Modifica ora' })
    fireEvent.change(within(popup).getByLabelText('Fine'), { target: { value: '12:00' } })
    fireEvent.click(within(popup).getByRole('button', { name: 'Salva' }))
    await waitFor(() => expect(calendarMocks.deleteTemplate).toHaveBeenCalledWith({ id: 7, from: '2026-10-12', to: '2026-10-26' }))
    expect(calendarMocks.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ end_time: '12:00', valid_from: '2026-10-12', valid_to: '2026-10-26' }))
    expect(calendarMocks.createTemplate.mock.invocationCallOrder[0]).toBeLessThan(calendarMocks.deleteTemplate.mock.invocationCallOrder[0])
  })
  it('la modifica non allunga un\'ora oltre le settimane in cui valeva', async () => {
    calendarMocks.template = [{ id: 7, day_of_week: 0, start_time: '08:30', end_time: '10:30', materia: 'Anatomia', valid_from: '2026-10-12', valid_to: '2026-10-19' }]
    renderPage(); chooseRange()
    fireEvent.click(screen.getByTestId('calendar-event-tpl_7'))
    const popup = screen.getByRole('dialog', { name: 'Modifica ora' })
    fireEvent.change(within(popup).getByLabelText('Fine'), { target: { value: '12:00' } })
    fireEvent.click(within(popup).getByRole('button', { name: 'Salva' }))
    await waitFor(() => expect(calendarMocks.deleteTemplate).toHaveBeenCalled())
    expect(calendarMocks.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ valid_from: '2026-10-12', valid_to: '2026-10-19' }))
  })
  it('fuori intervallo impedisce modifiche e Fatto azzera la scelta', () => {
    renderPage(); chooseRange()
    calendarMocks.week = { ...week, start_date: '2026-10-26' }
    fireEvent.click(screen.getByRole('button', { name: 'Settimana successiva' }))
    expect(screen.getByText("Fuori dall'intervallo scelto")).toBeVisible()
    expect(screen.queryByRole('button', { name: /Aggiungi alle/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: "Togli quest'ora" })).not.toBeInTheDocument()
    const block = screen.getByTestId('calendar-event-tpl_7')
    expect(block).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(block)
    fireEvent.click(screen.getByTestId('calendar-day-header-Lun'))
    expect(screen.queryByTestId('calendar-event-popup')).not.toBeInTheDocument()
    expect(screen.queryByTestId('calendar-day-menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Fatto' }))
    expect(screen.queryByRole('button', { name: 'Cambia intervallo di settimane' })).not.toBeInTheDocument()
    expect(screen.queryByText("Fuori dall'intervallo scelto")).not.toBeInTheDocument()
  })
  it('riapre la scelta dalla pillola e il riepilogo mostra l’anno del lunedì', () => {
    renderPage(); chooseRange()
    fireEvent.click(screen.getByRole('button', { name: 'Cambia intervallo di settimane' }))
    expect(screen.getByRole('button', { name: 'Modifica queste settimane' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
    fireEvent.click(screen.getByRole('button', { name: 'Riepilogo della settimana' }))
    expect(screen.getByTestId('calendar-week-popup')).toHaveTextContent('Settimana 42 · 12–16 ottobre 2026')
  })
})

it('nel riepilogo a cavallo di Capodanno usa l’anno del lunedì', () => {
  render(<WeekInfoPopup weekLabel="29 dicembre–2 gennaio" weekStart="2025-12-29" weekNumber="1"
    summary={{ hours_total: 0, recorded_count: 0, skip_count: 0, modified_hours_count: 0, to_recover: [] }}
    anchor={{ x: 100, y: 100, width: 20, height: 20 }} onClose={vi.fn()} />)
  expect(screen.getByTestId('calendar-week-popup')).toHaveTextContent('Settimana 1 · 29 dicembre–2 gennaio 2025')
})

it('la vista giorno fuori intervallo conserva le informazioni e impedisce il clic di modifica', () => {
  const onOpenEvent = vi.fn()
  render(<CalendarDayList days={[dummyDay]} selectedDayIndex={0} onSelectDayIndex={vi.fn()} readOnly onOpenEvent={onOpenEvent} />)
  const block = screen.getByTestId('calendar-mobile-event-tpl_1')
  expect(block).toHaveAttribute('aria-disabled', 'true')
  expect(block).toHaveTextContent('DATA MINING')
  fireEvent.click(block)
  expect(onOpenEvent).not.toHaveBeenCalled()
})
