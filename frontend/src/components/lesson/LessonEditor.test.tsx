import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { createRef } from 'react'
import { AudioProvider } from './audio'
import { LessonEditor, type LessonEditorActions } from './LessonEditor'

const upload = vi.hoisted(() => ({ started: null as null | ((task: Promise<void>) => void) }))
vi.mock('./lessonImages', () => ({ lessonImageUploads: (options: { started: (task: Promise<void>) => void }) => { upload.started = options.started; return [] } }))
const calls = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn(), remove: vi.fn() }))
vi.mock('@/api/client', async (original) => ({ ...await original<typeof import('@/api/client')>(), api: { GET: vi.fn().mockResolvedValue({ data: {}, response: new Response('{}', { status: 200 }) }), POST: calls.post, PUT: calls.put, DELETE: calls.remove } }))
vi.mock('@atomic-editor/editor', () => ({ AtomicCodeMirrorEditor: ({ markdownSource, onMarkdownChange, readOnly }: { markdownSource: string; onMarkdownChange: (s: string) => void; readOnly: boolean }) => <textarea aria-label="Editor" defaultValue={markdownSource} readOnly={readOnly} onChange={(e) => onMarkdownChange(e.target.value)} /> }))
vi.mock('./Enrichment', () => ({ EnrichmentPortals: () => null }))
vi.mock('./DocumentMenu', () => ({ DocumentMenu: ({ children }: { children: React.ReactNode }) => children }))
beforeEach(() => { vi.clearAllMocks(); calls.post.mockResolvedValue({ data: { token: 'lease' }, response: { ok: true } }); calls.put.mockResolvedValue({ data: { changed: true }, response: { ok: true } }); calls.remove.mockResolvedValue({ data: { message: 'ok' }, response: { ok: true } }) })
it('salva subito il testo corrente e libera il lease prima di una decisione', async () => {
  const actions = createRef<LessonEditorActions>()
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={query}><MemoryRouter><AudioProvider><LessonEditor lessonId={1} document={{ markdown: 'Prima', html: '', sections: [], final: false, pending: false }} hasAudio={false} ready locked={false} actionsRef={actions} /></AudioProvider></MemoryRouter></QueryClientProvider>)
  fireEvent.change(screen.getByLabelText('Editor'), { target: { value: 'Dopo' } })
  await act(() => actions.current!.flush())
  expect(calls.put).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/document/draft', expect.objectContaining({ body: { markdown: 'Dopo', lease_token: 'lease' } }))
  expect(calls.remove).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/document/lease', expect.objectContaining({ params: { path: { lesson_id: 1 }, query: { token: 'lease' } } }))
  expect(calls.put.mock.invocationCallOrder[0]).toBeLessThan(calls.remove.mock.invocationCallOrder[0])
})
it('propaga gli errori del salvataggio e conserva il lease', async () => {
  calls.put.mockRejectedValueOnce(new Error('Salvataggio fallito'))
  const actions = createRef<LessonEditorActions>()
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><AudioProvider><LessonEditor lessonId={1} document={{ markdown: 'Prima', html: '', sections: [], final: false, pending: false }} hasAudio={false} ready locked={false} actionsRef={actions} /></AudioProvider></MemoryRouter></QueryClientProvider>)
  fireEvent.change(screen.getByLabelText('Editor'), { target: { value: 'Dopo' } })
  await act(async () => { await expect(actions.current!.flush()).rejects.toThrow('API non raggiungibile') })
  expect(calls.remove).not.toHaveBeenCalled()
})

it('attende la fine dei caricamenti prima di salvare e liberare il lease', async () => {
  const actions = createRef<LessonEditorActions>()
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><AudioProvider><LessonEditor lessonId={1} document={{ markdown: 'Prima', html: '', sections: [], final: false, pending: false }} hasAudio={false} ready locked={false} actionsRef={actions} /></AudioProvider></MemoryRouter></QueryClientProvider>)
  let finish!: () => void
  act(() => upload.started!(new Promise<void>((resolve) => { finish = resolve })))
  fireEvent.change(screen.getByLabelText('Editor'), { target: { value: 'Dopo' } })
  let flushed!: Promise<void>
  act(() => { flushed = actions.current!.flush() })
  expect(calls.put).not.toHaveBeenCalled()
  await act(async () => { finish(); await flushed })
  expect(calls.put).toHaveBeenCalledOnce()
})

it('blocca il testo durante la classificazione e lo sblocca alla fine del job', () => {
  const query = new QueryClient()
  const component = (locked: boolean) => <QueryClientProvider client={query}><MemoryRouter><AudioProvider><LessonEditor lessonId={1} document={{ markdown: 'Testo completo', html: '', sections: [], final: false, pending: false }} hasAudio={false} ready locked={locked} /></AudioProvider></MemoryRouter></QueryClientProvider>
  const view = render(component(true))
  expect(screen.getByRole('img', { name: 'Sola lettura' })).toBeInTheDocument()
  expect(screen.getByLabelText('Editor')).toHaveAttribute('readonly')
  expect(screen.queryByRole('toolbar')).toBeNull()
  view.rerender(component(false))
  expect(screen.queryByRole('img', { name: 'Sola lettura' })).toBeNull()
  expect(screen.getByLabelText('Editor')).not.toHaveAttribute('readonly')
  expect(screen.getByRole('toolbar', { name: 'Strumenti dell’editor' })).toBeVisible()
})
