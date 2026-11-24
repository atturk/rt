import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { cleanComment } from '@/lib/recall'
import { LightweightSession } from './LightweightSession'
import { RecallAnswersPage } from './RecallAnswersPage'

const mockNextMutateAsync = vi.fn()
const mockAnswerMutateAsync = vi.fn()
const mockSeenMutateAsync = vi.fn().mockResolvedValue({})
const mockHistoryRefetch = vi.fn()
let mockHistoryAnswers: any[] = []

vi.mock('@/components/JobProgress', () => ({
  JobProgress: ({ label, onFinished }: { label: string; onFinished: (state: string) => void }) => (
    <button type="button" onClick={() => onFinished('succeeded')}>
      {label}
    </button>
  ),
}))

vi.mock('@/api/recallRules', () => ({
  useRecallRules: () => ({ data: { votes_enabled: true } }),
}))

vi.mock('@/api/hooks', () => ({
  useLesson: vi.fn(() => ({
    data: { id: 1, materia: 'Fisiologia', titolo: 'Respirazione' },
  })),
  useLessons: vi.fn(() => ({ data: [] })),
  useIssues: vi.fn(() => ({ data: { items: [], pending: 0 } })),
}))

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useRecallTypes: () => ({ data: actual.BASE_RECALL_TYPES }),
    useRecallOverview: () => ({ data: { questions: { mirata: { pending: 5 } } } }),
    useSubjectRecall: () => ({ data: null }),
    useRecallQuestions: () => ({ data: { questions: [] } }),
    useNextQuestion: () => ({ mutateAsync: mockNextMutateAsync, isPending: false }),
    useSubjectNext: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useAnswerSeen: () => ({ mutateAsync: mockSeenMutateAsync, isPending: false }),
    useAnswer: () => ({ mutateAsync: mockAnswerMutateAsync, isPending: false }),
    useAnswerVoice: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useVote: () => ({ mutate: vi.fn(), isPending: false }),
    useRegenerateQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSkip: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useEndSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSubjectEnd: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useRestorable: () => ({ data: { asked: 0, wrong: 0 } }),
    useRestoreQuestions: () => ({ mutate: vi.fn(), isPending: false }),
    useRecallHistory: () => ({
      data: {
        questions: [{ id: 'q1', question_text: 'Qual è il ruolo del surfactante?', type: 'mirata' }],
        answers: mockHistoryAnswers,
      },
      refetch: mockHistoryRefetch,
      isPending: false,
    }),
  }
})

describe('cleanComment helper', () => {
  it('strips leading parameter scores from comment when hasScores is true', () => {
    const raw = 'Correttezza: 90%\nCompletezza: 80%\nAttinenza: 75%\n\nOttima spiegazione.'
    expect(cleanComment(raw, true)).toBe('Ottima spiegazione.')
  })

  it('preserves text as is when hasScores is false', () => {
    const raw = 'Correttezza: 90%\nCompletezza: 80%\n\nTesto originale'
    expect(cleanComment(raw, false)).toBe(raw)
  })
})

describe('Recall Evaluation and Follow-up Flow in LightweightSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHistoryAnswers = []
  })

  it('renders 3 parameter tags row above comment and shows follow-up box', async () => {
    const question = {
      id: 'q1',
      type: 'mirata',
      question_text: 'Qual è il ruolo del surfactante polmonare?',
      unit_ids: ['1.1'],
      remaining: 3,
    }
    mockNextMutateAsync.mockResolvedValue(question)
    mockAnswerMutateAsync.mockResolvedValue({
      job: { job_id: 'job-123' },
    })

    mockHistoryAnswers = [
      {
        question_id: 'q1',
        answer_text: 'Riduce la tensione superficiale.',
        evaluation: 'Correttezza: 85%\nCompletezza: 70%\nAttinenza: 90%\n\nBuona risposta, ma incompleta.',
        outcome: 'parziale',
        correttezza: 85,
        completezza: 70,
        attinenza: 90,
        domanda_followup: 'Quali cellule producono il surfactante?',
      },
    ]
    mockHistoryRefetch.mockResolvedValue({ data: { answers: mockHistoryAnswers } })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <LightweightSession lessonId={1} />
        </BrowserRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('Qual è il ruolo del surfactante polmonare?')).toBeInTheDocument()
    })

    // Write answer and submit
    const input = screen.getByPlaceholderText(/Scrivi qui la tua risposta/i)
    fireEvent.change(input, { target: { value: 'Riduce la tensione superficiale.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rispondi' }))

    // Trigger evaluation finish
    await waitFor(() => {
      expect(screen.getByText('Valutazione della risposta')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Valutazione della risposta'))

    // Verify 3 tags are rendered
    await waitFor(() => {
      expect(screen.getByTestId('recall-eval-scores')).toBeInTheDocument()
      expect(screen.getByText('Correttezza 85%')).toBeInTheDocument()
      expect(screen.getByText('Completezza 70%')).toBeInTheDocument()
      expect(screen.getByText('Attinenza 90%')).toBeInTheDocument()
    })

    // Verify cleaned comment is shown (without redundant prefix)
    expect(screen.getByText('Buona risposta, ma incompleta.')).toBeInTheDocument()

    // Verify follow-up box is present
    expect(screen.getByTestId('recall-followup-box')).toBeInTheDocument()
    expect(screen.getByText('Quali cellule producono il surfactante?')).toBeInTheDocument()

    // Prossima should not be present while followup is pending
    expect(screen.queryByRole('button', { name: 'Prossima' })).not.toBeInTheDocument()

    // Test "Salta" clears the followup and reveals Prossima
    mockAnswerMutateAsync.mockResolvedValue({ ok: true })
    const skipBtn = screen.getByTestId('recall-followup-skip')
    fireEvent.click(skipBtn)

    expect(mockAnswerMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        questionId: 'q1',
        skipFollowup: true,
      }),
    )

    await waitFor(() => {
      expect(screen.queryByTestId('recall-followup-box')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Prossima' })).toBeInTheDocument()
    })
  })

  it('shows "Cosa mancava" with parte_mancante after clicking Salta on followup', async () => {
    const question = {
      id: 'q1',
      type: 'mirata',
      question_text: 'Qual è il ruolo del surfactante polmonare?',
      unit_ids: ['1.1'],
      remaining: 3,
    }
    mockNextMutateAsync.mockResolvedValue(question)
    mockAnswerMutateAsync.mockResolvedValue({ job: { job_id: 'job-123' } })

    mockHistoryAnswers = [
      {
        question_id: 'q1',
        answer_text: 'Riduce la tensione superficiale.',
        evaluation: 'Correttezza: 80%\nCompletezza: 60%\nAttinenza: 90%\n\nBuon inizio, manca un aspetto chiave.',
        outcome: 'parziale',
        correttezza: 80,
        completezza: 60,
        attinenza: 90,
        domanda_followup: 'Quali cellule intervengono nella sua produzione?',
        parte_mancante: null,
      },
    ]
    mockHistoryRefetch.mockResolvedValue({ data: { answers: mockHistoryAnswers } })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <LightweightSession lessonId={1} />
        </BrowserRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('Qual è il ruolo del surfactante polmonare?')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/Scrivi qui la tua risposta/i), {
      target: { value: 'Riduce la tensione superficiale.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Rispondi' }))

    await waitFor(() => {
      expect(screen.getByText('Valutazione della risposta')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Valutazione della risposta'))

    await waitFor(() => {
      expect(screen.getByTestId('recall-followup-box')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('recall-missing-part')).not.toBeInTheDocument()

    // Salta restituisce parte_mancante
    mockAnswerMutateAsync.mockResolvedValue({
      quiz: {
        message: 'Approfondimento saltato.',
        parte_mancante: 'I pneumociti di tipo II sintetizzano e secernono il surfactante.',
      },
    })
    fireEvent.click(screen.getByTestId('recall-followup-skip'))

    await waitFor(() => {
      expect(screen.getByTestId('recall-missing-part')).toBeInTheDocument()
    })
    expect(screen.getByText('Cosa mancava')).toBeInTheDocument()
    expect(
      screen.getByText('I pneumociti di tipo II sintetizzano e secernono il surfactante.'),
    ).toBeInTheDocument()
  })

  it('shows updated followup scores and comment as main evaluation and keeps initial evaluation in recap', async () => {
    const question = {
      id: 'q1',
      type: 'mirata',
      question_text: 'Qual è il ruolo del surfactante polmonare?',
      unit_ids: ['1.1'],
      remaining: 3,
    }
    mockNextMutateAsync.mockResolvedValue(question)
    mockAnswerMutateAsync.mockResolvedValue({
      job: { job_id: 'job-followup' },
    })

    mockHistoryAnswers = [
      {
        question_id: 'q1',
        answer_text: 'Riduce la tensione superficiale.',
        evaluation: 'Correttezza: 85%\nCompletezza: 60%\nAttinenza: 90%\n\nCommento iniziale.',
        outcome: 'corretta',
        correttezza: 85,
        completezza: 60,
        attinenza: 90,
        domanda_followup: null,
        followup_question: 'Quali cellule producono il surfactante?',
        followup_answer: 'I pneumociti di tipo II.',
        followup_evaluation: 'Correttezza: 95%\nCompletezza: 90%\nAttinenza: 95%\n\nOttimo approfondimento completo.',
        followup_correttezza: 95,
        followup_completezza: 90,
        followup_attinenza: 95,
      },
    ]
    mockHistoryRefetch.mockResolvedValue({ data: { answers: mockHistoryAnswers } })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <LightweightSession lessonId={1} />
        </BrowserRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('Qual è il ruolo del surfactante polmonare?')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/Scrivi qui la tua risposta/i), {
      target: { value: 'Riduce la tensione superficiale.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Rispondi' }))

    await waitFor(() => {
      expect(screen.getByText('Valutazione della risposta')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Valutazione della risposta'))

    await waitFor(() => {
      expect(screen.getByTestId('recall-eval-scores')).toHaveTextContent('Completezza 90%')
      expect(screen.getByTestId('recall-eval-scores')).toHaveTextContent('Correttezza 95%')
      expect(screen.getByTestId('recall-eval-scores')).toHaveTextContent('Attinenza 95%')
    })

    expect(screen.getByText('Giusto.')).toBeInTheDocument()
    expect(screen.getByText('Ottimo approfondimento completo.')).toBeInTheDocument()

    const recap = screen.getByTestId('recall-followup-recap')
    expect(recap).toHaveTextContent('Quali cellule producono il surfactante?')
    expect(recap).toHaveTextContent('I pneumociti di tipo II.')
    expect(recap).toHaveTextContent('Prima valutazione: Correttezza 85% · Completezza 60% · Attinenza 90%')
    expect(recap).toHaveTextContent('Commento iniziale.')

    // Il commento iniziale non è nel commento principale fuori dal riepilogo
    const resultCard = screen.getByTestId('recall-result-card')
    expect(resultCard.querySelectorAll('p').length).toBeGreaterThan(0)
    expect(recap.contains(screen.getByText('Commento iniziale.'))).toBe(true)
  })

  it('renders scores and followup recap in RecallAnswersPage', async () => {
    mockHistoryAnswers = [
      {
        attempt_id: 'att-1',
        question_id: 'q1',
        answer_text: 'Riduce la tensione superficiale.',
        evaluation: 'Correttezza: 85%\nCompletezza: 70%\nAttinenza: 90%\n\nBuona risposta.',
        outcome: 'parziale',
        answered_at: '2026-11-05T12:00:00Z',
        correttezza: 85,
        completezza: 70,
        attinenza: 90,
        followup_question: 'Quali cellule producono il surfactante?',
        followup_answer: 'I pneumociti di tipo II.',
      },
    ]

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <RecallAnswersPage />
        </BrowserRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('answer-row')).toBeInTheDocument()
    })

    // Expand answer
    fireEvent.click(screen.getByTestId('answer-row'))

    await waitFor(() => {
      expect(screen.getByTestId('answer-eval-scores')).toBeInTheDocument()
      expect(screen.getByText('Correttezza 85%')).toBeInTheDocument()
      expect(screen.getByText('Completezza 70%')).toBeInTheDocument()
      expect(screen.getByText('Attinenza 90%')).toBeInTheDocument()
      expect(screen.getByText('Buona risposta.')).toBeInTheDocument()
      expect(screen.getByTestId('answer-followup-recap')).toBeInTheDocument()
      expect(screen.getByText('Quali cellule producono il surfactante?')).toBeInTheDocument()
      expect(screen.getByText('I pneumociti di tipo II.')).toBeInTheDocument()
    })
  })

  it('shows Correttezza 70% badge and strips Correttezza: line for custom question types', async () => {
    const question = {
      id: 'q-custom',
      type: 'personalizzata',
      custom_type: 'problema-calcolo',
      question_text: 'Calcola il gap anionico del paziente.',
      unit_ids: ['2.1'],
      remaining: 2,
    }
    mockNextMutateAsync.mockResolvedValue(question)
    mockAnswerMutateAsync.mockResolvedValue({ job: { job_id: 'job-custom' } })

    mockHistoryAnswers = [
      {
        question_id: 'q-custom',
        answer_text: 'Gap = 16 mEq/L.',
        evaluation: 'Conclusione corretta, manca un passaggio del ragionamento.',
        outcome: 'parziale',
        correttezza: 70,
        completezza: 60,
        attinenza: null,
        domanda_followup: 'Come confronti il risultato con i valori normali?',
      },
    ]
    mockHistoryRefetch.mockResolvedValue({ data: { answers: mockHistoryAnswers } })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <LightweightSession lessonId={1} />
        </BrowserRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText('Calcola il gap anionico del paziente.')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/Scrivi qui la tua risposta/i), {
      target: { value: 'Gap = 16 mEq/L.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Rispondi' }))

    await waitFor(() => {
      expect(screen.getByText('Valutazione della risposta')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Valutazione della risposta'))

    await waitFor(() => {
      expect(screen.getByTestId('recall-eval-scores')).toBeInTheDocument()
    })
    const scores = screen.getByTestId('recall-eval-scores')
    expect(scores).toHaveTextContent('Correttezza 70%')
    expect(scores).toHaveTextContent('Completezza 60%')
    expect(scores).not.toHaveTextContent('Attinenza')

    const resultCard = screen.getByTestId('recall-result-card')
    expect(resultCard).toHaveTextContent('Conclusione corretta, manca un passaggio del ragionamento.')
    expect(resultCard).not.toHaveTextContent('Correttezza:')
    expect(screen.getByTestId('recall-followup-box')).toBeInTheDocument()
  })
})
