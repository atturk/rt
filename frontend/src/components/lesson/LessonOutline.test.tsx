import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { Schemas } from '@/api/client'
import { LessonOutline } from './LessonOutline'

const calls = vi.hoisted(() => ({ approve: vi.fn(), suspend: vi.fn(), revise: vi.fn(), phone: false }))
vi.mock('@/api/jobs', () => ({
  useApproveOutline: () => ({ mutate: calls.approve }),
  useSuspendOutline: () => ({ mutateAsync: calls.suspend }),
  useReviseOutline: () => ({ mutateAsync: calls.revise }),
  useJob: () => ({ data: undefined }),
  invalidateAfterJob: vi.fn(),
}))
vi.mock('@/lib/phone', () => ({ useIsPhone: () => calls.phone }))
const tree: Schemas['Outline'] = { lesson_title: 'Lezione', approved: false, timer_suspended: false, expires_at: '2026-10-03T20:00:10Z', timer_seconds: 10, macro_sections: [{ id: '1', title: 'Sezione', units: [{ id: '1.1', title: 'Unità', key_concepts: ['pH'], start_segment_id: 's1', end_segment_id: 's2' }] }] }
function mount(outline = tree, refresh = vi.fn().mockResolvedValue(undefined)) {
  const client = new QueryClient()
  const component = (o: Schemas['Outline']) => <QueryClientProvider client={client}><LessonOutline key={o.expires_at} lessonId={1} outline={o} busy={false} mock refresh={refresh} /></QueryClientProvider>
  const view = render(component(outline))
  return { ...view, refresh, replace: (o: Schemas['Outline']) => view.rerender(component(o)) }
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-03T20:00:00Z')); vi.clearAllMocks(); calls.phone = false
  calls.suspend.mockResolvedValue(undefined); calls.revise.mockResolvedValue({ job_id: 'revision' })
})
afterEach(() => vi.useRealTimers())

it('segue expires_at e allo zero rilegge la scaletta senza approvare dal browser', async () => {
  const { refresh } = mount()
  expect(screen.getByRole('button', { name: 'Approva (10)' })).toBeInTheDocument()
  await act(async () => { vi.advanceTimersByTime(11000) })
  expect(refresh).toHaveBeenCalledOnce()
  expect(calls.approve).not.toHaveBeenCalled()
})
it('il focus lascia il timer attivo; scrivere lo sospende una volta e rigenera dopo la conferma del server', async () => {
  let finish!: () => void
  calls.suspend.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve }))
  mount()
  fireEvent.focus(screen.getByLabelText('Oppure chiedi modifiche'))
  expect(calls.suspend).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Oppure chiedi modifiche'), { target: { value: 'Dividi' } })
  fireEvent.change(screen.getByLabelText('Oppure chiedi modifiche'), { target: { value: 'Dividi in due' } })
  expect(calls.suspend).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: 'Approva' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Rigenera con queste modifiche' }))
  expect(calls.revise).not.toHaveBeenCalled()
  await act(async () => { finish() })
  expect(calls.revise).toHaveBeenCalledWith({ feedback: 'Dividi in due', mock: true })
})
it('riparte con il nuovo expires_at dopo la revisione e azzera la richiesta precedente', async () => {
  const view = mount()
  await act(async () => { fireEvent.change(screen.getByLabelText('Oppure chiedi modifiche'), { target: { value: 'Dividi' } }) })
  expect(screen.getByRole('button', { name: 'Approva' })).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(1000))
  view.replace({ ...tree, expires_at: '2026-10-03T20:00:11Z' })
  expect(screen.getByRole('button', { name: 'Approva (10)' })).toBeInTheDocument()
  expect(screen.getByLabelText('Oppure chiedi modifiche')).toHaveValue('')
})
it('rispetta la sospensione persistita e sul telefono apre le modifiche senza fermare il timer', async () => {
  calls.phone = true
  mount({ ...tree, timer_suspended: true })
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.getByRole('button', { name: 'Approva' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Chiedi modifiche' }))
  expect(screen.getByRole('textbox')).toBeInTheDocument()
  expect(calls.suspend).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Approva' }))
  expect(calls.approve).toHaveBeenCalledOnce()
})
it('non accoda la revisione se il server non riesce a sospendere il timer', async () => {
  calls.suspend.mockRejectedValue(new Error('Sospensione fallita'))
  mount()
  await act(async () => { fireEvent.change(screen.getByLabelText('Oppure chiedi modifiche'), { target: { value: 'Dividi' } }) })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Rigenera con queste modifiche' })) })
  expect(calls.revise).not.toHaveBeenCalled()
})
