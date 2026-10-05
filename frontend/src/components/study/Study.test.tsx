import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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
  recall_questions: 3,
}

const UNITS = [
  { id: '1.1', title: 'Continuità didattica', html: '<p>Contenuto 1</p>', questions: 2, pending: {} },
  { id: '1.2', title: 'Acidosi metabolica', html: '<p>Contenuto 2</p>', questions: 1, pending: {} },
  { id: '2.1', title: 'Prelievo arterioso', html: '<p>Contenuto 3</p>', questions: 0, pending: {} },
]

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useStudyLesson: () => ({
      data: { id: 1, units: UNITS, has_audio: false },
      isPending: false,
      isError: false,
    }),
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
    expect(screen.getByRole('link', { name: 'Apri la lezione ›' })).toHaveAttribute('href', '/lezioni/1')

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

  it('nessun effetto delle frecce nella fase domande', () => {
    localStorage.clear()
    renderStudy()
    // Passa alla fase domande
    const quizBtn = screen.getByTestId('study-quiz')
    fireEvent.click(quizBtn)
    expect(screen.getByTestId('study-questions')).toBeInTheDocument()

    // Premi freccia destra
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    // Resta nella fase domande
    expect(screen.getByTestId('study-questions')).toBeInTheDocument()
  })
})
