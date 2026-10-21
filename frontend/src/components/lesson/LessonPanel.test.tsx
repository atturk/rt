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

it('usa il contenitore PN1 staccato con classe di animazione rt-panel-container', () => {
  render(<Panels />)
  fireEvent.click(screen.getByRole('button', { name: 'dettagli' }))
  const panel = screen.getByTestId('lesson-panel')
  expect(panel).toHaveClass('rt-panel-container')
  expect(panel.querySelector('.rt-panel-body-switch')).toBeInTheDocument()
})

it('la maniglia c’è solo con Arricchimento, trascinando cambia --rt-panel-width e torna a 24rem alla chiusura', () => {
  render(<Panels />)

  // In dettagli non c'è il separatore
  fireEvent.click(screen.getByRole('button', { name: 'dettagli' }))
  expect(screen.queryByRole('separator', { name: 'Larghezza del pannello' })).toBeNull()

  // In arricchimento c'è il separatore
  fireEvent.click(screen.getByRole('button', { name: 'arricchimento' }))
  const handle = screen.getByRole('separator', { name: 'Larghezza del pannello' })
  expect(handle).toBeInTheDocument()
  expect(handle).toHaveAttribute('aria-orientation', 'vertical')

  // Frecce tastiera (Left allarga, Right restringe)
  const initialWidth = Number(handle.getAttribute('aria-valuenow'))
  fireEvent.keyDown(handle, { key: 'ArrowLeft' })
  expect(Number(handle.getAttribute('aria-valuenow'))).toBe(initialWidth + 32)
  expect(document.documentElement.style.getPropertyValue('--rt-panel-width')).toBe(`${initialWidth + 32}px`)
  expect(localStorage.getItem('rt.panel.enrichment.width')).toBe(String(initialWidth + 32))

  // Trascinamento con pointer
  fireEvent.pointerDown(handle, { clientX: 500, pointerId: 1 })
  fireEvent.pointerMove(handle, { clientX: 450 }) // Spostamento a sinistra di 50px -> allarga di 50px
  fireEvent.pointerUp(handle, { pointerId: 1 })
  const newWidth = initialWidth + 32 + 50
  expect(Number(handle.getAttribute('aria-valuenow'))).toBe(newWidth)
  expect(document.documentElement.style.getPropertyValue('--rt-panel-width')).toBe(`${newWidth}px`)
  expect(localStorage.getItem('rt.panel.enrichment.width')).toBe(String(newWidth))

  // Doppio clic resetta a 24rem (384px)
  fireEvent.doubleClick(handle)
  expect(Number(handle.getAttribute('aria-valuenow'))).toBe(384)
  expect(document.documentElement.style.getPropertyValue('--rt-panel-width')).toBe('384px')

  // Chiudendo il pannello, torna a 24rem
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi il pannello' }))
  expect(document.documentElement.style.getPropertyValue('--rt-panel-width')).toBe('24rem')
})

it('legge la larghezza salvata da localStorage per Arricchimento', () => {
  localStorage.setItem('rt.panel.enrichment.width', '450')
  render(<Panels />)
  fireEvent.click(screen.getByRole('button', { name: 'arricchimento' }))
  const handle = screen.getByRole('separator', { name: 'Larghezza del pannello' })
  expect(handle).toHaveAttribute('aria-valuenow', '450')
  expect(document.documentElement.style.getPropertyValue('--rt-panel-width')).toBe('450px')
})


