import { fireEvent, render, screen } from '@testing-library/react'
import { usePanelView, type PanelView } from '@/lib/lessonPanel'
import { LessonPanel } from './LessonPanel'
import type { Schemas } from '@/api/client'

vi.mock('./panels/DetailsPanel', () => ({ DetailsPanel: () => <span>Dettagli esistenti</span> }))
vi.mock('./panels/ReviewPanel', () => ({ ReviewPanel: () => <span>Verifica esistente</span> }))
vi.mock('./panels/QuestionsPanel', () => ({ QuestionsPanel: () => <span>Domande esistenti</span> }))
vi.mock('./panels/ClassifierPanel', () => ({ ClassifierPanel: () => <span>Classificatore esistente</span> }))
vi.mock('./panels/EnrichmentPanel', () => ({ EnrichmentPanel: () => <span>Arricchimento esistente</span> }))

function Panels() {
  const [view, setView] = usePanelView()
  return <>
    {(['dettagli', 'verifica', 'domande', 'classificatore', 'arricchimento'] as PanelView[]).map((v) =>
      <button key={v} onClick={() => setView(view === v ? null : v)}>{v}</button>)}
    {view && <LessonPanel view={view} lesson={{} as Schemas['LessonDetail']} sections={[]} editingDocument={false} onClose={() => setView(null)} />}
  </>
}

beforeEach(() => localStorage.clear())

it('apre un solo pannello, lo sostituisce e lo chiude con X o Esc', () => {
  render(<Panels />)
  expect(screen.queryByRole('complementary')).toBeNull()
  for (const view of ['domande', 'classificatore', 'arricchimento', 'dettagli', 'verifica']) {
    fireEvent.click(screen.getByRole('button', { name: view }))
    expect(screen.getAllByRole('complementary')).toHaveLength(1)
    expect(screen.getByTestId('lesson-panel')).toHaveAttribute('data-view', view)
  }
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByRole('complementary')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'domande' }))
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi il pannello' }))
  expect(screen.queryByRole('complementary')).toBeNull()
})

it('ricorda i nuovi pannelli e ignora valori sconosciuti', () => {
  localStorage.setItem('rt-lesson-side-panel', 'classificatore')
  const { unmount } = render(<Panels />)
  expect(screen.getByRole('complementary', { name: 'Classificatore' })).toBeInTheDocument()
  unmount()
  localStorage.setItem('rt-lesson-side-panel', 'sconosciuto')
  render(<Panels />)
  expect(screen.queryByRole('complementary')).toBeNull()
})
