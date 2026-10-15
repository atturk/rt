import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useNavigate } from 'react-router'
import { AudioProvider } from './audio'
import { LessonEditor } from './LessonEditor'

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
