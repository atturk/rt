import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as recallApi from '@/api/recall'
import { RecallAnswersPage } from './RecallAnswersPage'

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useRecallHistory: vi.fn(),
  }
})

describe('RecallAnswersPage', () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderPage(lessonId = '42') {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/lezioni/${lessonId}/risposte`]}>
          <Routes>
            <Route path="/lezioni/:lessonId/risposte" element={<RecallAnswersPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('mostra lo stato vuoto se non ci sono risposte', () => {
    vi.mocked(recallApi.useRecallHistory).mockReturnValue({
      data: { questions: [], answers: [] },
      isPending: false,
    } as never)

    renderPage()
    expect(screen.getByTestId('empty-answers')).toHaveTextContent('Nessuna risposta.')
  })

  it('raggruppa i tentativi della stessa domanda sotto la domanda e ordina per data decrescente', () => {
    vi.mocked(recallApi.useRecallHistory).mockReturnValue({
      data: {
        questions: [
          { id: 'q1', question_text: 'Domanda 1', type: 'mirata', unit_ids: ['1.1'], status: 'answered' },
          { id: 'q2', question_text: 'Domanda 2', type: 'quiz', unit_ids: ['1.2'], status: 'answered' },
        ],
        answers: [
          {
            attempt_id: 'a1_old',
            question_id: 'q1',
            answer_text: 'Primo tentativo domanda 1',
            outcome: 'sbagliata',
            answered_at: '2026-10-01T10:00:00Z',
            evaluation: 'Non corretta.',
          },
          {
            attempt_id: 'a1_new',
            question_id: 'q1',
            answer_text: 'Secondo tentativo domanda 1',
            outcome: 'corretta',
            answered_at: '2026-10-02T12:00:00Z',
            evaluation: 'Esatto!',
          },
          {
            attempt_id: 'a2',
            question_id: 'q2',
            answer_text: 'Risposta domanda 2',
            outcome: 'parziale',
            answered_at: '2026-10-02T11:00:00Z',
            evaluation: 'Incompleta.',
          },
        ],
      },
      isPending: false,
    } as never)

    renderPage()

    // Due gruppi di domande
    const groups = screen.getAllByTestId('question-group')
    expect(groups).toHaveLength(2)

    // Domanda 1 ha il tentativo più recente (12:00 vs 11:00) quindi viene prima
    expect(groups[0]).toHaveAttribute('data-question-id', 'q1')
    expect(groups[1]).toHaveAttribute('data-question-id', 'q2')

    // Sotto q1 ci sono due righe di tentativi: il più recente in alto
    const q1Rows = screen.getAllByTestId('answer-row')
    expect(q1Rows).toHaveLength(3) // 2 per q1 + 1 per q2
    expect(q1Rows[0]).toHaveTextContent('Secondo tentativo domanda 1')
    expect(q1Rows[1]).toHaveTextContent('Primo tentativo domanda 1')
  })

  it('espande la valutazione al clic sulla riga del tentativo', () => {
    vi.mocked(recallApi.useRecallHistory).mockReturnValue({
      data: {
        questions: [
          { id: 'q1', question_text: 'Domanda 1', type: 'mirata', unit_ids: ['1.1'], status: 'answered' },
        ],
        answers: [
          {
            attempt_id: 'a1',
            question_id: 'q1',
            answer_text: 'La mia risposta',
            outcome: 'corretta',
            answered_at: '2026-10-02T10:00:00Z',
            evaluation: 'Spiegazione dettagliata della correzione.',
          },
        ],
      },
      isPending: false,
    } as never)

    renderPage()

    expect(screen.queryByTestId('answer-evaluation')).not.toBeInTheDocument()

    // Clic sulla riga
    fireEvent.click(screen.getByTestId('answer-row'))
    expect(screen.getByTestId('answer-evaluation')).toBeInTheDocument()
    expect(screen.getByTestId('answer-evaluation')).toHaveTextContent('Spiegazione dettagliata della correzione.')

    // Clic per richiudere
    fireEvent.click(screen.getByTestId('answer-row'))
    expect(screen.queryByTestId('answer-evaluation')).not.toBeInTheDocument()
  })

  it('filtra per esito (sbagliate, parziali, corrette)', () => {
    vi.mocked(recallApi.useRecallHistory).mockReturnValue({
      data: {
        questions: [
          { id: 'q1', question_text: 'Domanda 1', type: 'mirata', unit_ids: ['1.1'], status: 'answered' },
          { id: 'q2', question_text: 'Domanda 2', type: 'quiz', unit_ids: ['1.2'], status: 'answered' },
        ],
        answers: [
          {
            attempt_id: 'a1',
            question_id: 'q1',
            answer_text: 'Risposta sbagliata',
            outcome: 'sbagliata',
            answered_at: '2026-10-01T10:00:00Z',
          },
          {
            attempt_id: 'a2',
            question_id: 'q2',
            answer_text: 'Risposta corretta',
            outcome: 'corretta',
            answered_at: '2026-10-02T10:00:00Z',
          },
        ],
      },
      isPending: false,
    } as never)

    renderPage()
    expect(screen.getAllByTestId('answer-row')).toHaveLength(2)

    // Filtra per sbagliate
    fireEvent.click(screen.getByRole('button', { name: 'Sbagliate' }))
    expect(screen.getAllByTestId('answer-row')).toHaveLength(1)
    expect(screen.getByText('Risposta sbagliata')).toBeInTheDocument()
    expect(screen.queryByText('Risposta corretta')).not.toBeInTheDocument()

    // Filtra per corrette
    fireEvent.click(screen.getByRole('button', { name: 'Corrette' }))
    expect(screen.getAllByTestId('answer-row')).toHaveLength(1)
    expect(screen.getByText('Risposta corretta')).toBeInTheDocument()
    expect(screen.queryByText('Risposta sbagliata')).not.toBeInTheDocument()

    // Torna a tutte
    fireEvent.click(screen.getByRole('button', { name: 'Tutte' }))
    expect(screen.getAllByTestId('answer-row')).toHaveLength(2)
  })
})
