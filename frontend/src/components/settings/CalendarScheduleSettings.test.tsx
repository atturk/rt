afterEach(() => vi.restoreAllMocks())
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { calendarTransferApi } from '@/api/calendar'
import { CalendarScheduleSettings } from './CalendarScheduleSettings'

it.each([0, 3])('mostra la sostituzione solo con conflitti: %i', async conflicts => {
  const api = vi.spyOn(calendarTransferApi, 'import').mockResolvedValue({ subjects: 2, entries: 4, conflicts })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CalendarScheduleSettings onError={vi.fn()} /></QueryClientProvider>)
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
