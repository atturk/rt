import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { LightweightSession } from './LightweightSession'

const mockNextMutateAsync = vi.fn()
const mockSubjectNextMutateAsync = vi.fn()
const mockAnswerMutateAsync = vi.fn()
const mockVoteMutate = vi.fn()
const mockRegenerateMutateAsync = vi.fn()
const mockSkipMutateAsync = vi.fn()
const mockEndMutateAsync = vi.fn()
const mockHistoryRefetch = vi.fn()
const mockRestoreMutate = vi.fn()
let mockRestorableData = { asked: 0, wrong: 0 }
let mockOverviewData: { questions: Record<string, { pending: number }> } = {
  questions: {
    quiz: { pending: 15 },
    mirata: { pending: 8 },
  },
}

vi.mock('@/components/JobProgress', () => ({
  JobProgress: ({ label, onFinished }: { label: string; onFinished: (state: string) => void }) => (
    <button type="button" onClick={() => onFinished('succeeded')}>{label}</button>
  ),
}))

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
    data: mockOverviewData,
  })),
  useRecallHistory: vi.fn(() => ({
    data: { answers: [] },
    refetch: mockHistoryRefetch,
  })),
  useSubjectRecall: vi.fn(() => ({
    data: { lessons: [] },
  })),
  useNextQuestion: vi.fn(() => ({
    mutateAsync: mockNextMutateAsync,
    isPending: false,
  })),
  useSubjectNext: vi.fn(() => ({
    mutateAsync: mockSubjectNextMutateAsync,
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
  useRestorable: vi.fn(() => ({
    data: mockRestorableData,
  })),
  useRestoreQuestions: vi.fn(() => ({
    mutate: mockRestoreMutate,
    isPending: false,
    isError: false,
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

/** La sessione nel modo "unità" dello Studio (4.2.2b3). */
function renderUnitSession(onBack = vi.fn(), onDone = vi.fn(), pending: Record<string, number> = { quiz: 2, mirata: 1 }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <LightweightSession
          lessonId={1}
          unit={{ id: '1.2', title: 'Acidosi metabolica', pending, onBack, onDone, doneLabel: 'Unità successiva' }}
        />
      </BrowserRouter>
    </QueryClientProvider>,
  )
  return { onBack, onDone }
}

function renderSession(lessonId: number | undefined = 1, selectionIds?: number[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <LightweightSession lessonId={lessonId} selectionIds={selectionIds} />
      </BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('LightweightSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRestorableData = { asked: 0, wrong: 0 }
    mockOverviewData = {
      questions: {
        quiz: { pending: 15 },
        mirata: { pending: 8 },
      },
    }
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

  it('risposta aperta: aspetta la valutazione e mostra l’esito del valutatore', async () => {
    mockNextMutateAsync.mockResolvedValue({ ...sampleQuestion, id: 'q200', type: 'mirata', options: null, correct_index: null })
    mockAnswerMutateAsync.mockResolvedValue({ job: { job_id: 'j1' } })
    mockHistoryRefetch.mockResolvedValue({ data: { answers: [{ question_id: 'q200', outcome: 'parziale', evaluation: 'Manca il compenso respiratorio.' }] } })
    renderSession()

    fireEvent.change(await screen.findByLabelText('Risposta scritta'), { target: { value: 'Sotto 22' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rispondi' }))
    expect(await screen.findByRole('button', { name: 'Valutazione della risposta' })).toBeInTheDocument()
    expect(screen.queryByText('Giusto.')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Valutazione della risposta' }))
    expect(await screen.findByText('Risposta parziale.')).toBeInTheDocument()
    expect(screen.getByText('Manca il compenso respiratorio.')).toBeInTheDocument()
  })

  it('quiz: il clic sull’alternativa è la risposta e l’esito è quello del server', async () => {
    // Il server rivela la risposta giusta e la spiegazione: /recall/next non le manda.
    mockAnswerMutateAsync.mockResolvedValue({ quiz: {
      correct: true,
      question: { ...sampleQuestion, correct_index: 0, explanation: 'Sotto 22 mEq/L.' },
    } })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")
    expect(screen.queryByRole('button', { name: 'Rispondi' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Sotto 22 mEq/L').closest('button')!)

    expect(mockAnswerMutateAsync).toHaveBeenCalledWith({
      questionId: 'q100',
      choice: 0,
    })

    // Mostra scheda esito
    expect(await screen.findByTestId('recall-result-card')).toBeInTheDocument()
    expect(screen.getByText('Giusto.')).toBeInTheDocument()
    expect(screen.getByText("Sotto 22 mEq/L.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: "Rileggi l'unità 1.2" })).toHaveAttribute('href', '/lezioni/1#unit-1.2')
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

    // Mostra l'avanzamento del job invece di passare subito alla prossima
    expect(await screen.findByRole('button', { name: 'Rigenerazione della domanda' })).toBeInTheDocument()
  })

  it('salta la domanda al clic su Salta', async () => {
    mockSkipMutateAsync.mockResolvedValue({ message: 'ok' })
    renderSession()

    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    const saltaBtn = screen.getByRole('button', { name: 'Salta' })
    fireEvent.click(saltaBtn)

    expect(mockSkipMutateAsync).toHaveBeenCalledWith('q100')
    // la prossima esclude quella appena saltata
    await waitFor(() => expect(mockNextMutateAsync).toHaveBeenLastCalledWith({ qtype: 'quiz', excludeId: 'q100' }))
  })

  it('modo unità: chip coi conteggi, le vaste non ci sono e "Termina" torna allo studio', async () => {
    const { onBack } = renderUnitSession()
    await screen.findByText("Quale valore di bicarbonato definisce l'acidosi metabolica?")

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Acidosi metabolica')
    const types = screen.getByRole('group', { name: 'Tipo di domanda' })
    expect(types).not.toHaveTextContent('Vasta')
    expect(types.querySelector('[aria-pressed=true]')).toHaveTextContent('Mista 3')
    expect(screen.getByRole('button', { name: 'Quiz 2' })).toBeEnabled()
    // I tipi senza domande da porre restano spenti.
    expect(screen.getByRole('button', { name: 'Casi' })).toBeDisabled()

    // Prima della risposta si salta, "Prossima" non c'è ancora.
    expect(screen.getByRole('button', { name: 'Salta' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Prossima' })).not.toBeInTheDocument()

    // Termina: la domanda lasciata a metà torna fra quelle da porre e si torna allo studio.
    fireEvent.click(screen.getByRole('button', { name: 'Termina' }))
    await waitFor(() => expect(onBack).toHaveBeenCalled())
    expect(mockSkipMutateAsync).toHaveBeenCalledWith('q100')
  })

  it('modo unità: finite le domande si va avanti nello Studio', async () => {
    mockNextMutateAsync.mockRejectedValue(new ApiError(404, 'no_questions', 'Non ci sono domande da porre.'))
    const { onDone } = renderUnitSession()
    const done = await screen.findByTestId('recall-unit-done')
    expect(done).toHaveTextContent('Unità successiva')
    fireEvent.click(done)
    expect(onDone).toHaveBeenCalled()
  })

  it('pool vuoto: tipo già mista non mostra "Prova mista" (4.2.2b4 F3)', async () => {
    localStorage.setItem('rt-recall-last-type', 'mista')
    mockNextMutateAsync.mockRejectedValue(new ApiError(404, 'no_questions', 'Non ci sono domande da porre.'))
    renderSession(1)

    expect(await screen.findByTestId('recall-empty')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Prova mista' })).not.toBeInTheDocument()
    localStorage.clear()
  })

  it('pool vuoto: tipo diverso da mista e domande da porre > 0 mostra "Prova mista" (4.2.2b4 F3)', async () => {
    localStorage.setItem('rt-recall-last-type', 'quiz')
    mockNextMutateAsync.mockRejectedValue(new ApiError(404, 'no_questions', 'Non ci sono domande da porre.'))
    renderSession(1)

    expect(await screen.findByTestId('recall-empty')).toBeInTheDocument()
    const provalink = screen.getByRole('button', { name: 'Prova mista' })
    expect(provalink).toBeInTheDocument()
    fireEvent.click(provalink)
    expect(mockNextMutateAsync).toHaveBeenCalledWith({ qtype: 'mista', excludeId: undefined, unitId: undefined })
    localStorage.clear()
  })

  it('pool vuoto con una lezione e zero da porre: Genera domande e ripescaggio che riparte (4.2.2b4 F3)', async () => {
    mockOverviewData = { questions: {} }
    mockRestorableData = { asked: 4, wrong: 2 }
    mockNextMutateAsync.mockRejectedValue(new ApiError(404, 'no_questions', 'Non ci sono domande da porre.'))
    renderSession(1)

    expect(await screen.findByTestId('recall-empty')).toBeInTheDocument()
    // Nessun "Prova mista" perché zero da porre
    expect(screen.queryByRole('button', { name: 'Prova mista' })).not.toBeInTheDocument()

    // Pulsante "Genera domande"
    const generaLink = screen.getByRole('link', { name: 'Genera domande' })
    expect(generaLink).toHaveAttribute('href', '/lezioni/1?panel=domande')

    // Pulsanti ripescaggio con conteggio
    const wrongBtn = screen.getByRole('button', { name: 'Riproponi le sbagliate (2)' })
    const askedBtn = screen.getByRole('button', { name: 'Riproponi le poste (4)' })
    expect(wrongBtn).toBeInTheDocument()
    expect(askedBtn).toBeInTheDocument()

    // Clic sul ripescaggio: chiama restore.mutate e riparte la sessione
    fireEvent.click(wrongBtn)
    expect(mockRestoreMutate).toHaveBeenCalledWith('wrong', expect.objectContaining({ onSuccess: expect.any(Function) }))

    // Callback onSuccess chiama askNext
    const { onSuccess } = mockRestoreMutate.mock.calls[0][1]
    mockNextMutateAsync.mockResolvedValueOnce(sampleQuestion)
    onSuccess()
    expect(mockNextMutateAsync).toHaveBeenCalled()
  })

  it('selezione su più lezioni con pool vuoto: nessun pulsante genera né ripescaggio, solo testo (4.2.2b4 F3)', async () => {
    mockSubjectNextMutateAsync.mockRejectedValue(new ApiError(404, 'no_questions', 'Non ci sono domande da porre.'))
    renderSession(undefined, [1, 2])

    expect(await screen.findByTestId('recall-empty')).toBeInTheDocument()
    // Nessun link/pulsante Genera domande
    expect(screen.queryByRole('link', { name: 'Genera domande' })).not.toBeInTheDocument()
    // Nessun ripescaggio
    expect(screen.queryByRole('button', { name: /Riproponi/ })).not.toBeInTheDocument()
    // Testo che dice di generare dai rispettivi pannelli
    expect(screen.getByText(/Non ci sono domande da porre\. Puoi generare nuove domande dai pannelli delle rispettive lezioni\./)).toBeInTheDocument()
  })
})

it.each([false, true])('all’ultima domanda Fine mostra il finale senza next (unità: %s)', async (unit) => {
  vi.clearAllMocks()
  mockRestorableData = { asked: 1, wrong: 0 }
  mockNextMutateAsync.mockResolvedValue({ ...sampleQuestion, remaining: 0 })
  mockAnswerMutateAsync.mockResolvedValue({ quiz: { correct: true, question: sampleQuestion } })
  if (unit) renderUnitSession()
  else renderSession()
  fireEvent.click((await screen.findByText('Sotto 22 mEq/L')).closest('button')!)
  const finish = await screen.findByRole('button', { name: 'Fine' })
  expect(screen.queryByRole('button', { name: 'Prossima' })).not.toBeInTheDocument()
  fireEvent.click(finish)
  expect(await screen.findByTestId('recall-empty')).toBeVisible()
  if (unit) expect(screen.getByText('Hai finito le domande di questa unità')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Riproponi le poste (1)' })).toBeVisible()
  expect(mockNextMutateAsync).toHaveBeenCalledTimes(1)
})

it('il cambio tipo usa remaining della nuova domanda', async () => {
  vi.clearAllMocks()
  mockNextMutateAsync.mockResolvedValueOnce({ ...sampleQuestion, remaining: 0 })
    .mockResolvedValueOnce({ ...sampleQuestion, id: 'q101', remaining: 2 })
  mockAnswerMutateAsync.mockResolvedValue({ quiz: { correct: true, question: sampleQuestion } })
  renderUnitSession()
  await screen.findByText('Sotto 22 mEq/L')
  fireEvent.click(screen.getByRole('button', { name: /^Quiz/  }))
  await waitFor(() => expect(screen.getByTestId('recall-question')).toHaveAttribute('data-question-id', 'q101'))
  fireEvent.click(screen.getByText('Sotto 22 mEq/L').closest('button')!)
  expect(await screen.findByRole('button', { name: 'Prossima' })).toBeVisible()
})
