afterEach(() => vi.restoreAllMocks())
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { calendarTransferApi } from '@/api/calendar'
import { CalendarScheduleSettings } from './CalendarScheduleSettings'

it.each([0, 3])('mostra la sostituzione solo con conflitti: %i', async conflicts => {
  const api = vi.spyOn(calendarTransferApi, 'import').mockResolvedValue({ subjects: 2, entries: 4, conflicts })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CalendarScheduleSettings onError={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const file = new File(['{}'], 'orario.rtcal', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(JSON.stringify({ format: 'rt-calendar', version: 1 })) })
  await userEvent.upload(screen.getByLabelText('File dell’orario'), file)
  const action = await screen.findByRole('button', { name: conflicts ? 'Sostituisci' : 'Importa' })
  await waitFor(() => expect(action).toBeEnabled())
  expect(!!screen.queryByText('Sostituisce l’orario attuale')).toBe(!!conflicts)
  expect(api).toHaveBeenCalledWith({ format: 'rt-calendar', version: 1 }, true, undefined, undefined)
  fireEvent.click(action)
  await waitFor(() => expect(api).toHaveBeenCalledWith({ format: 'rt-calendar', version: 1 }, false, undefined, undefined))
})

it('.rtcal aperto popola il popup ma non chiama l import senza clic', async () => {
  const api = vi.spyOn(calendarTransferApi, 'import').mockResolvedValue({ subjects: 3, entries: 6, conflicts: 0 })
  const calendarData = { format: 'rt-calendar', version: 1, entries: [{ id: 1 }] }

  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[{ pathname: '/impostazioni/calendario', state: { importCalendarFile: { name: 'orario.rtcal', data: calendarData } } }]}>
        <CalendarScheduleSettings onError={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  )

  // Il popup "Importa orario" è aperto e compilato
  expect(screen.getByRole('dialog', { name: 'Importa orario' })).toBeInTheDocument()
  expect(screen.getByText(/orario\.rtcal/)).toBeInTheDocument()

  // Preview viene calcolato (chiamata con preview=true), ma l'import effettivo (preview=false) NON è chiamato
  await waitFor(() => {
    expect(api).toHaveBeenCalledWith(calendarData, true, undefined, undefined)
  })
  expect(api).not.toHaveBeenCalledWith(calendarData, false, undefined, undefined)
})
