import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { CalendarPage } from '@/routes/calendar'
import { type CalendarWeekView, type CalendarYearWeek } from '@/api/calendar'

const mocks = vi.hoisted(() => ({ currentDate: '', paste: vi.fn() }))
const event = { key: 'tpl_1', date: '2026-10-19', day_of_week: 0, start_time: '09:00', end_time: '11:00', start_hour: 9, end_hour: 11, materia: 'Biologia', docente: 'Rossi', status: 'seguire', is_recorded: false, is_modified: false }
const week = { start_date: '2026-10-19', week_number: '43', label: '19–23 ottobre', end_date: '2026-10-23', days: [{ date: '2026-10-19', day_of_week: 0, day_name: 'Lun', day_number: 19, month_name: 'ottobre', is_today: false, status: '', events: [event] }], summary: { hours_total: 2, recorded_count: 0, skip_count: 0, modified_hours_count: 0 } } satisfies CalendarWeekView
const year = ['2026-10-19', '2026-10-26', '2026-11-02'].map((start_date, i) => ({ start_date, week_number: 43 + i,
  days: [{ date: start_date, status: '', events: [{ start_hour: 9, end_hour: 11, materia: 'Biologia', status: 'seguire', is_recorded: false, is_modified: false }] }],
})) satisfies CalendarYearWeek[]
vi.mock('@/api/calendar', async original => {
  const actual = await original<typeof import('@/api/calendar')>()
  const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn() })
  return { ...actual, useCalendarWeek: (date: string) => { mocks.currentDate = date; return { data: week } },
    useCalendarYear: () => ({ data: year }), useCalendarTemplate: () => ({ data: [] }),
    useCreateOverride: mutation, useDeleteOverride: mutation, useCreateTemplateEntry: mutation, useDeleteTemplateEntry: mutation,
    useSetDayState: mutation, useSetEntryState: mutation, useLinkLesson: mutation,
    usePasteCalendar: () => ({ mutateAsync: mocks.paste, isPending: false }),
  }
})
function open() {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><CalendarPage /></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => { sessionStorage.clear(); mocks.paste.mockReset(); mocks.paste.mockResolvedValue({ weeks: [] }) })
it('Vai alla settimana apre la griglia condivisa e naviga al lunedì scelto', () => {
  open()
  fireEvent.click(screen.getByRole('button', { name: 'Vai alla settimana' }))
  const dialog = screen.getByRole('dialog', { name: 'Vai alla settimana' })
  fireEvent.click(dialog.querySelector('[data-week="2026-11-02"]')!)
  expect(mocks.currentDate).toBe('2026-11-02')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('la vista annuale seleziona, copia e incolla su più settimane con conferma', async () => {
  open()
  fireEvent.click(screen.getByRole('button', { name: 'Anno' }))
  const annual = screen.getByTestId('calendar-year-view')
  const row = (date: string) => annual.querySelector<HTMLButtonElement>(`[data-week="${date}"]`)!
  fireEvent.click(row('2026-10-19'))
  expect(row('2026-10-19')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Copia lo stampo di questa settimana' }))
  expect(await screen.findByTestId('calendar-clipboard-notice')).toHaveAccessibleName('Stampo copiato')
  expect(JSON.parse(sessionStorage.getItem('rt:calendar-clipboard')!)).toMatchObject({ sourceStart: '2026-10-19', entries: [{ materia: 'Biologia', docente: 'Rossi' }] })
  fireEvent.click(row('2026-10-26'))
  fireEvent.click(screen.getByRole('button', { name: 'Seleziona più settimane' }))
  fireEvent.click(row('2026-11-02'))
  fireEvent.click(screen.getByRole('button', { name: 'Incolla lo stampo della settimana 43' }))
  expect(screen.getByText('2 settimane hanno già un orario. Sostituirlo?')).toBeInTheDocument()
  expect(mocks.paste).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Sostituisci' }))
  await waitFor(() => expect(mocks.paste).toHaveBeenCalledWith({ weeks: ['2026-10-26', '2026-11-02'], entries: [expect.objectContaining({ materia: 'Biologia' })] }))
  expect(sessionStorage.getItem('rt:calendar-view')).toBe('year')
  fireEvent.click(screen.getByRole('button', { name: 'Fatto' }))
  fireEvent.keyDown(row('2026-11-02'), { key: 'Enter' })
  expect(screen.queryByTestId('calendar-year-view')).not.toBeInTheDocument()
  expect(mocks.currentDate).toBe('2026-11-02')
})
it('su touch la matita si apre, si richiude con un secondo tocco e con un tocco fuori', () => {
  const original = window.matchMedia
  window.matchMedia = vi.fn((query: string) => ({ matches: query.includes('max-width') || query === '(hover: none)', addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia
  try {
    open()
    const pencil = screen.getByRole('button', { name: 'Modifica orario' })
    fireEvent.click(pencil)
    expect(pencil).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(pencil)
    expect(pencil).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(pencil)
    fireEvent.pointerDown(document.body)
    expect(pencil).toHaveAttribute('aria-expanded', 'false')
  } finally { window.matchMedia = original }
})

it('Vai alla settimana dalla vista annuale apre la settimana scelta', () => {
  open()
  fireEvent.click(screen.getByRole('button', { name: 'Anno' }))
  fireEvent.click(screen.getByRole('button', { name: 'Vai alla settimana' }))
  const dialog = screen.getByRole('dialog', { name: 'Vai alla settimana' })
  fireEvent.click(dialog.querySelector('[data-week="2026-11-02"]')!)
  expect(screen.queryByTestId('calendar-year-view')).not.toBeInTheDocument()
  expect(mocks.currentDate).toBe('2026-11-02')
})
