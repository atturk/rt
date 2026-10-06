import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from './client'
import { recallKeys, type StudyLesson } from './recall'
import { useStudyStatus } from './studyProgress'

it('aggiorna subito lo Studio, ripristina lo stato dopo un errore e invalida l’elenco', async () => {
  let fail!: (error: Error) => void
  vi.spyOn(api, 'PUT').mockImplementation(() => new Promise((_resolve, reject) => { fail = reject }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const key = recallKeys.study(1)
  const initial = { id: 1, ready: true, has_audio: false, units: [{ id: '1.1', title: 'Prima', html: '', questions: 0, pending: {}, status: 'da-imparare' }] } as StudyLesson
  client.setQueryData(key, initial)
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  function Probe() {
    const mutation = useStudyStatus(1)
    return <button onClick={() => mutation.mutate({ unitId: '1.1', status: 'appreso' })}>Cambia stato</button>
  }
  render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Cambia stato' }))
  await waitFor(() => expect(client.getQueryData<StudyLesson>(key)?.units[0].status).toBe('appreso'))
  fail(new Error('Salvataggio non riuscito'))
  await waitFor(() => expect(client.getQueryData(key)).toEqual(initial))
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['lessons'] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: key })
  vi.restoreAllMocks()
})
