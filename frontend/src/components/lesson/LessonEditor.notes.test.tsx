import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useNavigate } from 'react-router'
import { AudioProvider } from './audio'
import { LessonEditor } from './LessonEditor'
import { EditorView } from '@codemirror/view'

const run = vi.hoisted(() => vi.fn().mockResolvedValue({ job_id: 'review' }))
vi.mock('@/api/hooks', async (original) => ({ ...await original<typeof import('@/api/hooks')>(), useRunJob: () => ({ mutateAsync: run }) }))

vi.mock('@atomic-editor/editor', async () => {
  const { useLayoutEffect, useRef } = await import('react')
  const { EditorView } = await import('@codemirror/view')
  const { lessonStudyNotes } = await import('./lessonStudyNotes')
  return { AtomicCodeMirrorEditor: ({ markdownSource, editorHandleRef }: { markdownSource: string; editorHandleRef: { current: unknown } }) => {
    const root = useRef<HTMLDivElement>(null)
    useLayoutEffect(() => {
      const view = new EditorView({ doc: markdownSource, parent: root.current!, extensions: lessonStudyNotes })
      editorHandleRef.current = { getContentDOM: () => view.contentDOM }
      return () => { editorHandleRef.current = null; view.destroy() }
    }, [markdownSource, editorHandleRef])
    return <div ref={root} />
  } }
})
vi.mock('@/api/studyNotes', () => ({ useStudyNotes: () => ({ data: notes }) }))
vi.mock('./Enrichment', () => ({ EnrichmentPortals: () => null }))
const notes = [{ id: 1, kind: 'chiedi', unit_id: '1.1', anchor_state: 'trovata', current_quote: 'Passaggio scelto' }]

function Navigation() {
  const navigate = useNavigate()
  return <><button onClick={() => navigate('?panel=note&note=1')}>Apri note</button><button onClick={() => navigate('?panel=fonti&note=1')}>Chiudi note</button></>
}

it('mostra i segni soltanto con il pannello note aperto, anche se resta note=1', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  Object.defineProperty(Range.prototype, 'getClientRects', { configurable: true, value: () => [] })
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', { configurable: true, value: () => new DOMRect() })
  const query = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
  const { container, unmount } = render(<QueryClientProvider client={query}><MemoryRouter><AudioProvider>
    <Navigation />
    <LessonEditor lessonId={1} document={{ markdown: '## 1. Macro\n\n### 1.1 Test\n\n00:00\n\nPassaggio scelto e resto.', html: '', sections: [], final: false, pending: false }} hasAudio={false} ready locked={false} />
  </AudioProvider></MemoryRouter></QueryClientProvider>)
  expect(container.querySelector('.rt-sn')).toBeNull()
  fireEvent.click(screen.getByText('Apri note'))
  await waitFor(() => expect(container.querySelector('.rt-sn-selected')).toHaveTextContent('Passaggio scelto'))
  fireEvent.click(screen.getByText('Chiudi note'))
  await waitFor(() => expect(container.querySelector('.rt-sn')).toBeNull())
  unmount()
  vi.unstubAllGlobals()
})

it.each([{ button: 2 }, { button: 0, ctrlKey: true }])('editor senza selezione: il menu usa il paragrafo con %j', async (mouse) => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const markdown = '## 1. Macro\n\n### 1.1 Test\n\n00:00\n\nPassaggio scelto e resto.\nSeconda riga dello stesso paragrafo.'
  vi.spyOn(EditorView.prototype, 'posAtCoords').mockReturnValue(markdown.indexOf('Passaggio'))
  vi.spyOn(EditorView.prototype, 'coordsAtPos').mockReturnValue({ left: 0, right: 10, top: 0, bottom: 10 })
  const query = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
  const { container, unmount } = render(<QueryClientProvider client={query}><MemoryRouter><AudioProvider>
    <LessonEditor lessonId={1} document={{ markdown, html: '', sections: [{ unit_id: '1.1', title: 'Test', start_segment_id: 'seg_1', end_segment_id: 'seg_1' }], final: false, pending: false }} hasAudio={false} ready locked={false} />
  </AudioProvider></MemoryRouter></QueryClientProvider>)
  const content = container.querySelector('.cm-content')!
  fireEvent.mouseDown(content, mouse)
  fireEvent.contextMenu(content, { ctrlKey: mouse.ctrlKey })
  expect(screen.getByRole('menu', { name: 'Azioni sul testo' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Verifica questa parte' }))
  await waitFor(() => expect(run).toHaveBeenLastCalledWith({ type: 'review_part', parts: [expect.objectContaining({ unit_id: '1.1', anchor: expect.objectContaining({ quote: 'Passaggio scelto e resto.\nSeconda riga dello stesso paragrafo.' }) })] }))
  unmount()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
