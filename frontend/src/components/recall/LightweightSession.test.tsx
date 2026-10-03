import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { LightweightSession } from './LightweightSession'

const mockNextMutateAsync = vi.fn()
const mockAnswerMutateAsync = vi.fn()
const mockVoteMutate = vi.fn()
const mockRegenerateMutateAsync = vi.fn()
const mockSkipMutateAsync = vi.fn()
const mockEndMutateAsync = vi.fn()

vi.mock('@/api/hooks', () => ({
  useLesson: vi.fn(() => ({
    data: { id: 1, materia: 'Fisiologia', titolo: 'Emogasanalisi e acidosi' },
  })),
  useLessons: vi.fn(() => ({
    data: [],
  })),
}))

vi.mock('@/api/recall', () => ({
  useRecallOverview: vi.fn(() => ({
    data: {
      questions: {
        quiz: { pending: 15 },
        mirata: { pending: 8 },
      },
    },
  })),
  useRecallHistory: vi.fn(() => ({
    data: { answers: [] },
  })),
  useSubjectRecall: vi.fn(() => ({
    data: { lessons: [] },
  })),
  useNextQuestion: vi.fn(() => ({
    mutateAsync: mockNextMutateAsync,
    isPending: false,
  })),
  useSubjectNext: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  useAnswer: vi.fn(() => ({
    mutateAsync: mockAnswerMutateAsync,
    isPending: false,
  })),
  useAnswerVoice: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  useVote: vi.fn(() => ({
    mutate: mockVoteMutate,
    isPending: false,
  })),
  useRegenerateQuestion: vi.fn(() => ({
    mutateAsync: mockRegenerateMutateAsync,
    isPending: false,
  })),
  useSkip: vi.fn(() => ({
    mutateAsync: mockSkipMutateAsync,
    isPending: false,
  })),
  useEndSession: vi.fn(() => ({
    mutateAsync: mockEndMutateAsync,
    isPending: false,
  })),
  useSubjectEnd: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
}))

const sampleQuestion = {
  id: 'q100',
  type: 'quiz',
  status: 'pending',
  unit_ids: ['1.2'],
  question_text: "Quale valore di bicarbonato definisce l'acidosi metabolica?",
  options: ['Sotto 22 mEq/L', 'Sotto 26 mEq/L', 'Sopra 30 mEq/L', 'Non cambia'],
  correct_index: 0,
  explanation: 'Sotto 22 mEq/L.',
}

function renderSession(lessonId = 1) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <LightweightSession lessonId={lessonId} />
      </BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('LightweightSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockNextMutateAsync.mockResolvedValue(sampleQuestion)
  })

  it('mostra intestazione, chips del tipo e carica la prima domanda', async () => {
    renderSession()

    expect(screen.getByText(/Esci/i)).toBeInTheDocument()
    expect(screen.getByText(/23 da porre/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mista' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Quiz' })).toBeInTheDocument()

    // Domanda caricata
    expect(await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")).toBeInTheDocument()
    expect(screen.getByText('A.')).toBeInTheDocument()
    expect(screen.getByText('Sotto 22 mEq/L')).toBeInTheDocument()
  })

  it('risponde a un quiz e mostra la scheda esito', async () => {
    mockAnswerMutateAsync.mockResolvedValue({ correct: true })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    // Seleziona la prima opzione
    const optA = screen.getByText('Sotto 22 mEq/L').closest('button')!
    fireEvent.click(optA)

    // Clic su Rispondi
    const rispondiBtn = screen.getByRole('button', { name: 'Rispondi' })
    fireEvent.click(rispondiBtn)

    expect(mockAnswerMutateAsync).toHaveBeenCalledWith({
      questionId: 'q100',
      choice: 0,
    })

    // Mostra scheda esito
    expect(await screen.findByTestId('recall-result-card')).toBeInTheDocument()
    expect(screen.getByText('Giusto.')).toBeInTheDocument()
    expect(screen.getByText("Sotto 22 mEq/L.")).toBeInTheDocument()
  })

  it('invia Non lo so quando cliccato', async () => {
    mockAnswerMutateAsync.mockResolvedValue({ correct: false })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    const dontKnowBtn = screen.getByRole('button', { name: 'Non lo so' })
    fireEvent.click(dontKnowBtn)

    expect(mockAnswerMutateAsync).toHaveBeenCalledWith({
      questionId: 'q100',
      dontKnow: true,
    })

    expect(await screen.findByTestId('recall-result-card')).toBeInTheDocument()
    expect(screen.getByText('Sbagliata.')).toBeInTheDocument()
  })

  it('apre la modale Domanda scartata per 👎 con motivi di scarto', async () => {
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    const thumbsDownBtn = screen.getByRole('button', { name: 'Domanda da scartare' })
    fireEvent.click(thumbsDownBtn)

    // Modale aperta
    expect(screen.getByRole('dialog', { name: 'Domanda scartata' })).toBeInTheDocument()
    expect(screen.getByText('Sbagliata')).toBeInTheDocument()
    expect(screen.getByText('Troppi indizi')).toBeInTheDocument()

    // Seleziona motivo
    fireEvent.click(screen.getByText('Troppo facile'))

    // Invia con Prossima
    const prossimaBtn = screen.getAllByRole('button', { name: 'Prossima' }).pop()!
    fireEvent.click(prossimaBtn)

    expect(mockVoteMutate).toHaveBeenCalledWith({
      questionId: 'q100',
      vote: 'down',
      reasons: ['troppo_facile'],
    })
  })

  it('apre la modale Commenta e invia la rigenerazione', async () => {
    mockRegenerateMutateAsync.mockResolvedValue({ job_id: 'j1' })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    const commentBtn = screen.getByRole('button', { name: 'Commenta' })
    fireEvent.click(commentBtn)

    expect(screen.getByRole('dialog', { name: 'Commenta la domanda' })).toBeInTheDocument()

    const commentInput = screen.getByLabelText(/Cosa non va, o cosa vorresti invece/i)
    fireEvent.change(commentInput, { target: { value: 'Chiedi sui casi clinici' } })

    const sendBtn = screen.getByRole('button', { name: /Invia e rigenera/i })
    fireEvent.click(sendBtn)

    expect(mockRegenerateMutateAsync).toHaveBeenCalledWith({
      questionId: 'q100',
      comment: 'Chiedi sui casi clinici',
    })
  })

  it('salta la domanda al clic su Salta', async () => {
    mockSkipMutateAsync.mockResolvedValue({ message: 'ok' })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    const saltaBtn = screen.getByRole('button', { name: 'Salta' })
    fireEvent.click(saltaBtn)

    expect(mockSkipMutateAsync).toHaveBeenCalledWith('q100')
  })
})
