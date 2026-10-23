import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { api } from './client'
import { recallKeys, type StudyLesson } from './recall'
import { STUDY_STATUS_SAVE_DELAY, useStudyStatus, type StudyStatus } from './studyProgress'

const key = recallKeys.study(1)
const initial = { id: 1, ready: true, has_audio: false, units: [{ id: '1.1', title: 'Prima', html: '', questions: 0, pending: {}, status: 'da-imparare' }] } as StudyLesson

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(key, initial)
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  function Probe() {
    const mutation = useStudyStatus(1)
    return <>{(['in-apprendimento', 'appreso', 'da-imparare'] as StudyStatus[]).map(status =>
      <button key={status} onClick={() => mutation.mutate({ unitId: '1.1', status })}>{status}</button>)}</>
  }
  const view = render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>)
  const status = () => client.getQueryData<StudyLesson>(key)?.units[0].status
  return { client, invalidate, view, status }
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

it('cambia subito lo stato e salva solo l’ultimo, quando i tasti si fermano', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: {}, response: new Response() } as never)
  const { invalidate, status } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'in-apprendimento' }))
  expect(status()).toBe('in-apprendimento')
  fireEvent.click(screen.getByRole('button', { name: 'appreso' }))
  expect(status()).toBe('appreso')
  expect(put).not.toHaveBeenCalled()
  await act(async () => { await vi.advanceTimersByTimeAsync(STUDY_STATUS_SAVE_DELAY) })
  expect(put).toHaveBeenCalledTimes(1)
  expect(put.mock.calls[0][1]).toMatchObject({ body: { status: 'appreso' } })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['lessons'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: key })
})

it('tornati allo stato di partenza non salva niente', async () => {
  const put = vi.spyOn(api, 'PUT')
  const { status } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'appreso' }))
  fireEvent.click(screen.getByRole('button', { name: 'da-imparare' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(STUDY_STATUS_SAVE_DELAY) })
  expect(put).not.toHaveBeenCalled()
  expect(status()).toBe('da-imparare')
})

it('ripristina lo stato salvato se il server non risponde', async () => {
  vi.spyOn(api, 'PUT').mockRejectedValue(new Error('Salvataggio non riuscito'))
  const { client } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'appreso' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(STUDY_STATUS_SAVE_DELAY) })
  expect(client.getQueryData(key)).toEqual(initial)
})

it('uscendo dallo Studio salva subito lo stato in attesa', () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: {}, response: new Response() } as never)
  const { view } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'appreso' }))
  view.unmount()
  expect(put).toHaveBeenCalledTimes(1)
})
