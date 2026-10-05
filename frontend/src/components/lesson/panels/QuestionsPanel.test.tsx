import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { BrowserRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { QuestionsPanel } from './QuestionsPanel'

const mockGenerateMutate = vi.fn()
const mockDeleteMutate = vi.fn()
const mockSelectUnitsMutate = vi.fn()
const mockStatusMutate = vi.fn()
const mockRestoreMutate = vi.fn()
const mockEditMutate = vi.fn()

vi.mock('@/api/recall', () => ({
  useRecallOverview: vi.fn(() => ({
    data: {
      questions: {
        quiz: { pending: 2, asked: 1 },
        mirata: { pending: 1 },
      },
    },
  })),
  useRecallQuestions: vi.fn((_id: number, _reveal: boolean) => ({
    isPending: false,
    isError: false,
    data: {
      questions: [
        {
          id: 'q1',
          type: 'quiz',
          status: 'pending',
          outcome: null,
          question_text: 'Quale valore definisce acidosi?',
          unit_ids: ['1.2'],
        },
        {
          id: 'q2',
          type: 'mirata',
          status: 'asked',
          outcome: 'corretta',
          question_text: 'Come si calcola il gap anionico?',
          unit_ids: ['1.3'],
        },
        {
          id: 'q3',
          type: 'vasta',
          status: 'pending',
          outcome: null,
          question_text: 'Descrivi la compensazione.',
          unit_ids: ['2.1'],
        },
      ],
      unit_titles: {
        '1.2': 'Acidosi',
        '1.3': 'Gap anionico',
        '2.1': 'Prelievo',
      },
    },
  })),
  useRecallHistory: vi.fn(() => ({
    data: {
      answers: [
        {
          question_id: 'q2',
          type: 'quiz',
          outcome: 'corretta',
          answered_at: '2026-10-02T10:00:00Z',
        },
      ],
    },
  })),
  useRecallUnits: vi.fn(() => ({
    data: {
      units: [
        { unit_id: '1.1', selected: true },
        { unit_id: '1.2', selected: true },
        { unit_id: '1.3', selected: false },
      ],
      selected: 2,
      custom: false,
    },
  })),
  useSelectRecallUnits: vi.fn(() => ({
    mutate: mockSelectUnitsMutate,
    isPending: false,
    isError: false,
  })),
  useGenerateRecall: vi.fn(() => ({
    mutate: mockGenerateMutate,
    isPending: false,
    isError: false,
  })),
  useDeleteQuestions: vi.fn(() => ({
    mutate: mockDeleteMutate,
    isPending: false,
    isError: false,
  })),
  useQuestionStatus: vi.fn(() => ({ mutate: mockStatusMutate, isPending: false, isError: false })),
  useRestoreQuestions: vi.fn(() => ({ mutate: mockRestoreMutate, isPending: false, isError: false })),
  useRestorable: vi.fn(() => ({ data: { asked: 2, wrong: 1 } })),
  useEditQuestion: vi.fn(() => ({ mutate: mockEditMutate, isPending: false, isError: false })),
  useRegenerateComment: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
}))

vi.mock('@/api/jobs', () => ({
  useJobs: vi.fn(() => ({
    data: [],
  })),
}))

function renderPanel(props: React.ComponentProps<typeof QuestionsPanel> = { lessonId: 1 }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <QuestionsPanel {...props} />
      </BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('QuestionsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mostra il riepilogo con conteggi per tipo e link al ripasso', () => {
    renderPanel()

    expect(screen.getByText(/2 domande da porre/i)).toBeInTheDocument()
    expect(screen.getByText(/Ultimo ripasso/i)).toHaveTextContent(/Ultimo ripasso: .+ · Mirata/)
    expect(screen.getByRole('link', { name: /Ripassa/i })).toHaveAttribute('href', '/lezioni/1/sessione')

    // 5 tipi nel grid
    expect(screen.getByRole('button', { name: /Mostra solo quiz/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Mostra solo mirate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Mostra solo vaste/i })).toBeInTheDocument()

    // Elenco domande
    expect(screen.getByText('Quale valore definisce acidosi?')).toBeInTheDocument()
    expect(screen.getByText('Come si calcola il gap anionico?')).toBeInTheDocument()
    expect(screen.getByText('Descrivi la compensazione.')).toBeInTheDocument()
  })

  it('filtra per tipo al clic sul bottone del tipo', () => {
    renderPanel()

    const quizBtn = screen.getByRole('button', { name: /Mostra solo quiz/i })
    fireEvent.click(quizBtn)

    expect(screen.getByText('Quale valore definisce acidosi?')).toBeInTheDocument()
    expect(screen.queryByText('Come si calcola il gap anionico?')).toBeNull()
    expect(screen.queryByText('Descrivi la compensazione.')).toBeNull()

    // Azzera filtro
    fireEvent.click(screen.getByText('Azzera filtro'))
    expect(screen.getByText('Come si calcola il gap anionico?')).toBeInTheDocument()
  })

  it('invia la generazione globale con tipo, conteggio e istruzioni', () => {
    renderPanel()

    const countInput = screen.getByLabelText('Quante')
    fireEvent.change(countInput, { target: { value: '5' } })

    const instructionsInput = screen.getByLabelText('Direttive (facoltative)')
    fireEvent.change(instructionsInput, { target: { value: 'Focalizzati sui valori' } })

    const generaBtn = screen.getByRole('button', { name: 'Genera' })
    fireEvent.click(generaBtn)

    expect(mockGenerateMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        qtype: 'quiz',
        count: 5,
        instructions: 'Focalizzati sui valori',
      }),
      expect.any(Object),
    )
  })

  it('elimina una domanda dal menu contestuale della riga', () => {
    renderPanel()

    const menuBtns = screen.getAllByRole('button', { name: 'Azioni sulla domanda' })
    fireEvent.click(menuBtns[0])

    const deleteBtn = screen.getByRole('menuitem', { name: /Elimina/i })
    fireEvent.click(deleteBtn)

    expect(mockDeleteMutate).toHaveBeenCalledWith(['q1'])
  })

  it('filtra per stato e contrae l’elenco delle domande della lezione (4.2.2b3)', () => {
    renderPanel()
    const toggle = screen.getByTestId('questions-list-toggle')
    expect(toggle).toHaveTextContent('Domande della lezione (3)')
    expect(screen.getByTestId('questions-list')).toBeInTheDocument()

    // Solo quelle poste: resta la mirata già risposta.
    fireEvent.click(within(screen.getByRole('group', { name: 'Filtra per stato' })).getByRole('button', { name: 'Poste' }))
    expect(screen.getByTestId('questions-list')).toHaveTextContent('Come si calcola il gap anionico?')
    expect(screen.getByTestId('questions-list')).not.toHaveTextContent('Quale valore definisce acidosi?')
    expect(toggle).toHaveTextContent('Domande della lezione (1)')

    // Contratta: l'elenco non si vede più.
    fireEvent.click(toggle)
    expect(screen.getByTestId('questions-list-body')).not.toBeVisible()
  })

  it('riproponi le poste e solo quelle sbagliate (4.2.2b3)', () => {
    renderPanel()
    const restore = screen.getByTestId('questions-restore')
    fireEvent.click(within(restore).getByRole('button', { name: /Riproponi le poste \(2\)/ }))
    expect(mockRestoreMutate).toHaveBeenCalledWith('asked')
    fireEvent.click(within(restore).getByRole('button', { name: /Solo quelle sbagliate \(1\)/ }))
    expect(mockRestoreMutate).toHaveBeenCalledWith('wrong')
  })

  it('segna una domanda come posta dal menu della riga (4.2.2b3)', () => {
    renderPanel()
    fireEvent.click(screen.getAllByRole('button', { name: 'Azioni sulla domanda' })[0])
    fireEvent.click(screen.getByRole('menuitem', { name: /Segna come posta/ }))
    expect(mockStatusMutate).toHaveBeenCalledWith({ questionId: 'q1', status: 'asked' })

    // La domanda già posta offre invece di rimetterla fra quelle da porre.
    fireEvent.click(screen.getAllByRole('button', { name: 'Azioni sulla domanda' })[1])
    fireEvent.click(screen.getByRole('menuitem', { name: /Segna da porre/ }))
    expect(mockStatusMutate).toHaveBeenCalledWith({ questionId: 'q2', status: 'pending' })
  })

  it('gestisce la variante su selezione (Domande-Parte)', () => {
    const onClearSelection = vi.fn()
    renderPanel({
      lessonId: 1,
      selectedUnits: ['1.2', '1.3'],
      selectedText: 'Testo di esempio',
      onClearSelection,
    })

    // Mostra solo le unità 1.2 e 1.3
    expect(screen.getByText('Quale valore definisce acidosi?')).toBeInTheDocument()
    expect(screen.getByText('Come si calcola il gap anionico?')).toBeInTheDocument()
    expect(screen.queryByText('Descrivi la compensazione.')).toBeNull()

    // Form dedicato
    expect(screen.getByText('Nuove domande su 1.2 e 1.3')).toBeInTheDocument()

    // Genera per parte
    const generaBtn = screen.getByRole('button', { name: 'Genera' })
    fireEvent.click(generaBtn)

    expect(mockGenerateMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        unit_ids: ['1.2', '1.3'],
        selection: 'Testo di esempio',
        qtype: 'mirata',
        count: 3,
      }),
      expect.any(Object),
    )

    // Clear selection
    fireEvent.click(screen.getByText('Mostra tutte le domande'))
    expect(onClearSelection).toHaveBeenCalledTimes(1)
  })

  it('apre la modale per scegliere le unità del recaller e ne salva la selezione', () => {
    const onSwitchToClassifier = vi.fn()
    renderPanel({ lessonId: 1, onSwitchToClassifier })

    fireEvent.click(screen.getByRole('button', { name: 'Scegli' }))
    expect(screen.getByRole('dialog', { name: 'Unità per il recaller' })).toBeInTheDocument()

    // Clic su una casella
    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[2])
    expect(mockSelectUnitsMutate).toHaveBeenCalledWith(['1.1', '1.2', '1.3'])

    // Clic su Tutte (quello della modale: "Tutte" è anche un filtro di stato dell'elenco)
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Unità per il recaller' })).getByRole('button', { name: 'Tutte' }))
    expect(mockSelectUnitsMutate).toHaveBeenCalledWith(['1.1', '1.2', '1.3'])

    // Chiudi con Fine
    fireEvent.click(screen.getByRole('button', { name: 'Fine' }))

    // Rivedi le etichette chiama onSwitchToClassifier
    fireEvent.click(screen.getByRole('button', { name: 'Rivedi le etichette' }))
    expect(onSwitchToClassifier).toHaveBeenCalledTimes(1)
  })
})
