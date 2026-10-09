import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { StudyFlow } from './Study'
import type { Lesson } from '@/lib/format'

const LESSON: Lesson = {
  id: 1,
  materia: 'FISIOLOGIA',
  titolo: 'Emogasanalisi e acidosi',
  ora: '',
  data: '2026-10-02',
  folder_name: 'a',
  phases: { build: 'VALID', rewrite: 'VALID' },
  argomenti: '',
  docente: 'Rossi',
  path: '',
  duration_seconds: 3600,
  unit_count: 3,
  pending_issues: 0,
  recall_pending: 0,
  study_learned: 0,
  study_learning: 0, study_ignored: 0,
  recall_questions: 3,
}

const UNITS = [
  { id: '1.1', title: 'Continuità didattica', html: '<p>Contenuto 1</p>', questions: 2, pending: {} },
  { id: '1.2', title: 'Acidosi metabolica', html: '<p>Contenuto 2</p>', questions: 1, pending: {} },
  { id: '2.1', title: 'Prelievo arterioso', html: '<p>Contenuto 3</p>', questions: 0, pending: {} },
]

let mockSuggestions = false
const mockGenerate = vi.fn()
const progress = vi.hoisted(() => ({ status: vi.fn(), read: vi.fn() }))
vi.mock('@/api/studyProgress', () => ({
  useStudyStatus: () => ({ mutate: progress.status, isPending: false }),
  useStudyRead: () => ({ mutate: progress.read }),
}))
beforeEach(() => { vi.clearAllMocks(); mockSuggestions = false })
afterEach(() => vi.useRealTimers())

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useStudyLesson: () => ({
      data: { id: 1, units: UNITS.map(u => ({ ...u, suggested_qtype: 'mirata' })), has_audio: false, suggestions: mockSuggestions },
      isPending: false,
      isError: false,
    }),
    useGenerateForUnits: () => ({ mutate: mockGenerate, isPending: false, isError: false }),
  }
})

function renderStudy() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StudyFlow unit navigation', () => {
  it('le frecce ai limiti mostrano la fascia e annunciano il limite senza finire lo Studio', () => {
    localStorage.clear()
    renderStudy()
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByTestId('study-edge-left')).toBeInTheDocument()
    expect(screen.getByText('Prima unità')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Unità 3: Prelievo arterioso, Da imparare' }))
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByTestId('study-edge-right')).toBeInTheDocument()
    expect(screen.getByText('Ultima unità')).toBeInTheDocument()
    expect(screen.queryByTestId('study-done')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('2.1 Prelievo arterioso')
  })

  it('Esci segue l’unità aperta e il link accanto al titolo non c’è', () => {
    renderStudy()
    expect(screen.getByRole('link', { name: 'Esci' })).toHaveAttribute('href', '/lezioni/1#unit-1.1')
    fireEvent.click(screen.getByRole('button', { name: 'Unità 2: Acidosi metabolica, Da imparare' }))
    expect(screen.getByRole('link', { name: 'Esci' })).toHaveAttribute('href', '/lezioni/1#unit-1.2')
    expect(screen.queryByRole('link', { name: /^Apri la lezione$/ })).not.toBeInTheDocument()
  })

  it('S e il pulsante cambiano stato; S non agisce nei campi o con i modificatori', () => {
    renderStudy()
    fireEvent.click(screen.getByRole('button', { name: "Stato: da imparare" }))
    expect(progress.status).toHaveBeenCalledWith({ unitId: '1.1', status: 'in-apprendimento' })
    fireEvent.keyDown(window, { key: 's' })
    expect(progress.status).toHaveBeenCalledTimes(2)
    fireEvent.keyDown(window, { key: 's', ctrlKey: true })
    const input = document.createElement('input')
    document.body.appendChild(input)
    fireEvent.keyDown(input, { key: 's' })
    input.remove()
    expect(progress.status).toHaveBeenCalledTimes(2)
  })

  it('le barrette sono pulsanti accessibili e cambiano unità', () => {
    renderStudy()
    fireEvent.click(screen.getByRole('button', { name: 'Unità 2: Acidosi metabolica, Da imparare' }))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('1.2 Acidosi metabolica')
    expect(screen.getByRole('button', { name: 'Unità 2: Acidosi metabolica, Da imparare' })).toHaveAttribute('aria-current', 'step')
  })

  it('segna una lettura dopo tre secondi, una volta sola; una visita breve non conta', () => {
    vi.useFakeTimers()
    renderStudy()
    act(() => vi.advanceTimersByTime(2999))
    expect(progress.read).not.toHaveBeenCalled()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    act(() => vi.advanceTimersByTime(3000))
    expect(progress.read).toHaveBeenCalledExactlyOnceWith('1.2')
    act(() => vi.advanceTimersByTime(6000))
    expect(progress.read).toHaveBeenCalledOnce()
  })

  it('mostra il pulsante Unità 1 di 3 e apre l\'indice per navigare all\'unità 1.2', () => {
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
    const toggle = screen.getByTestId('unit-index-toggle')
    expect(toggle).toHaveTextContent('Unità 1 di 3')

    // Apri l'indice
    fireEvent.click(toggle)
    const menu = screen.getByTestId('unit-index-menu')
    expect(menu).toBeInTheDocument()
    expect(menu).toHaveTextContent('Sezione 1')
    expect(menu).toHaveTextContent('Sezione 2')

    // Clicca sull'unità 1.2
    const unit12Btn = screen.getByRole('menuitem', { name: /1.2 Acidosi metabolica/ })
    fireEvent.click(unit12Btn)

    // L'unità mostrata passa a 1.2
    expect(screen.getByRole('heading', { level: 2, name: '1.2 Acidosi metabolica' })).toBeInTheDocument()
    expect(screen.getByTestId('unit-index-toggle')).toHaveTextContent('Unità 2 di 3')
  })

  it('titolo senza posizione, apre e chiude il popup dei dettagli', () => {
    renderStudy()
    // Titolo senza "· unità 1 di 3"
    const titleBtn = screen.getByTestId('study-title-button')
    expect(titleBtn).toHaveTextContent('Emogasanalisi e acidosi')
    expect(titleBtn).not.toHaveTextContent('unità 1 di 3')

    // Clic apre il popup dei dettagli
    fireEvent.click(titleBtn)
    const popup = screen.getByTestId('study-details-popup')
    expect(popup).toBeInTheDocument()
    expect(popup).toHaveTextContent(/fisiologia/i)
    expect(popup).toHaveTextContent('Rossi')
    expect(popup).toHaveTextContent('3 · stai leggendo la 1')
    expect(popup).toHaveTextContent('1 h')
    expect(screen.getByRole('link', { name: 'Apri la lezione ›' })).toHaveAttribute('href', '/lezioni/1#unit-1.1')

    // Esc chiude il popup
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('study-details-popup')).not.toBeInTheDocument()
  })

  it('frecce ← e → cambiano unità nella fase di lettura', () => {
    localStorage.clear()
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    // Freccia destra passa a 1.2
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByRole('heading', { level: 2, name: '1.2 Acidosi metabolica' })).toBeInTheDocument()

    // Freccia destra passa a 2.1
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByRole('heading', { level: 2, name: '2.1 Prelievo arterioso' })).toBeInTheDocument()

    // Freccia sinistra torna a 1.2
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByRole('heading', { level: 2, name: '1.2 Acidosi metabolica' })).toBeInTheDocument()
  })

  it('nessun effetto delle frecce con tasti modificatori o con focus in un campo di testo', () => {
    localStorage.clear()
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    // Con Cmd/Ctrl/Alt premuti non si muove
    fireEvent.keyDown(window, { key: 'ArrowRight', metaKey: true })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'ArrowRight', ctrlKey: true })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    // Con focus in un input
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireEvent.keyDown(input, { key: 'ArrowRight' })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
    document.body.removeChild(input)
  })

  it('nessun effetto delle frecce se disattivate nella preferenza', () => {
    localStorage.setItem('rt-pref:study.highlighter', JSON.stringify({ color: 0, arrows: false }))
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
    localStorage.clear()
  })

  it('unità senza domande: "genera ora" apre il popup e lancia il job su quell’unità, niente study-next (4.2.2b3, 4.2.2b4)', () => {
    localStorage.clear()
    renderStudy()
    // L'unità 2.1 non ha domande.
    fireEvent.click(screen.getByTestId('unit-index-toggle'))
    fireEvent.click(screen.getByRole('menuitem', { name: /2.1 Prelievo arterioso/ }))
    const generate = screen.getByTestId('study-generate')
    expect(generate).toHaveTextContent('Nessuna domanda · genera ora')
    expect(screen.queryByTestId('study-next')).not.toBeInTheDocument()

    fireEvent.click(generate)
    fireEvent.click(screen.getByRole('button', { name: 'Caso clinico' }))
    fireEvent.change(screen.getByLabelText('Quante'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText(/Istruzioni aggiuntive/), { target: { value: 'solo sui valori soglia' } })
    fireEvent.click(screen.getByTestId('study-generate-start'))

    expect(mockGenerate).toHaveBeenCalledWith(
      { unitIds: ['2.1'], qtype: 'caso', count: 2, instructions: 'solo sui valori soglia' },
      expect.anything(),
    )
  })

  it('con domande mostra entrambi i pulsanti e il secondo apre il popup di generazione (4.2.2b4 F2)', () => {
    localStorage.clear()
    renderStudy()
    // L'unità 1.1 ha 2 domande
    expect(screen.getByTestId('study-quiz')).toHaveTextContent('Mettimi alla prova · 2')
    const generateBtn = screen.getByTestId('study-generate')
    expect(generateBtn).toBeInTheDocument()
    expect(screen.queryByTestId('study-next')).not.toBeInTheDocument()

    // Il secondo pulsante apre il popup di generazione
    fireEvent.click(generateBtn)
    expect(screen.getByTestId('study-generate-modal')).toBeInTheDocument()
  })

  it('nessun effetto delle frecce nella fase domande', () => {
    localStorage.clear()
    renderStudy()
    // Passa alla fase domande
    const quizBtn = screen.getByTestId('study-quiz')
    fireEvent.click(quizBtn)
    expect(screen.getByTestId('recall-session-page')).toBeInTheDocument()

    // Premi freccia destra
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    // Resta nella fase domande
    expect(screen.getByTestId('recall-session-page')).toBeInTheDocument()
  })

  it('swipe touch cambia unità nella fase di lettura (4.2.2b4 F1)', () => {
    localStorage.clear()
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    const column = screen.getByTestId('study-reading-column')

    // Swipe destra -> sinistra: da x=200 a x=80 (|dx| = 120 >= 60, dy = 5)
    fireEvent.pointerDown(column, { pointerType: 'touch', pointerId: 1, clientX: 200, clientY: 100 })
    fireEvent.pointerUp(column, { pointerType: 'touch', pointerId: 1, clientX: 80, clientY: 105 })

    expect(screen.getByRole('heading', { level: 2, name: '1.2 Acidosi metabolica' })).toBeInTheDocument()

    // Swipe sinistra -> destra: da x=80 a x=200 (|dx| = 120 >= 60, dy = 5)
    fireEvent.pointerDown(column, { pointerType: 'touch', pointerId: 2, clientX: 80, clientY: 100 })
    fireEvent.pointerUp(column, { pointerType: 'touch', pointerId: 2, clientX: 200, clientY: 105 })

    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
  })

  it('swipe touch ignorato con mouse o se disattivato da preferenza (4.2.2b4 F1)', () => {
    localStorage.clear()
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    const column = screen.getByTestId('study-reading-column')

    // Ignorato se pointerType === 'mouse'
    fireEvent.pointerDown(column, { pointerType: 'mouse', pointerId: 1, clientX: 200, clientY: 100 })
    fireEvent.pointerUp(column, { pointerType: 'mouse', pointerId: 1, clientX: 80, clientY: 105 })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()

    // Ignorato se arrows disattivate
    localStorage.setItem('rt-pref:study.highlighter', JSON.stringify({ color: 0, arrows: false }))
    renderStudy()
    fireEvent.pointerDown(column, { pointerType: 'touch', pointerId: 2, clientX: 200, clientY: 100 })
    fireEvent.pointerUp(column, { pointerType: 'touch', pointerId: 2, clientX: 80, clientY: 105 })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
    localStorage.clear()
  })
})

it.each([true, false])('popup Genera: consigliato presente e selezionato solo con Jev (%s)', suggestions => {
  mockSuggestions = suggestions
  renderStudy()
  fireEvent.click(screen.getByTestId('study-generate'))
  expect(screen.queryByRole('button', { name: /Consigliato/ })).not.toBeInTheDocument()
  if (suggestions) expect(screen.getByTestId('question-type-advice')).toHaveAttribute('aria-label', 'Consigliato da Jev')
  if (suggestions) expect(screen.getByRole('button', { name: 'Mirata' })).toHaveAttribute('aria-pressed', 'true')
  else expect(screen.queryByRole('button', { name: /Consigliato/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Quante'), { target: { value: '2' } })
  fireEvent.click(screen.getByTestId('study-generate-start'))
  expect(mockGenerate).toHaveBeenCalledWith({ unitIds: ['1.1'], qtype: suggestions ? 'mirata' : 'quiz', count: 2, instructions: '' }, expect.anything())
})

it('D apre il ripasso classico, Tornando allo Studio la zen resta accesa', () => {
  renderStudy()
  fireEvent.keyDown(window, { key: 'z' })
  fireEvent.keyDown(window, { key: 'd' })
  expect(screen.getByTestId('recall-session-page')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Torna allo studio' })[0])
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
  expect(screen.getByTestId('study-text')).toHaveAttribute('data-unit-id', '1.1')
})
