import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { QuestionEditModal } from './QuestionEditModal'
import type { RecallQuestionDetail } from '@/api/recall'

const mockEdit = vi.fn()
const mockRegenerate = vi.fn()

const QUIZ = {
  id: 'q1', type: 'quiz', status: 'pending', outcome: null, unit_ids: ['1.2'],
  question_text: 'Quale valore definisce acidosi?',
  options: ['pH < 7.35', 'pH > 7.45', 'pH 7.40', 'pH 7.42'],
  correct_index: 0,
  explanation: 'Sotto 7.35 il sangue è acido.',
} as unknown as RecallQuestionDetail

const MIRATA = { ...QUIZ, id: 'q2', type: 'mirata', options: null, correct_index: null, explanation: null, question_text: 'Spiega il gap anionico.' } as unknown as RecallQuestionDetail

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useRecallQuestions: vi.fn(() => ({ isError: false, data: { questions: [QUIZ, MIRATA] } })),
    useEditQuestion: vi.fn(() => ({ mutate: mockEdit, isPending: false, isError: false })),
    useRegenerateComment: vi.fn(() => ({ mutate: mockRegenerate, isPending: false, isError: false })),
  }
})

vi.mock('@/api/jobStatus', () => ({
  jobFinished: () => false,
  useJobStatus: vi.fn(() => ({ data: undefined })),
}))

function open(question: RecallQuestionDetail) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <QuestionEditModal lessonId={1} question={question} open onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('popup di modifica di una domanda', () => {
  it('quiz: salva testo, alternative e risposta giusta', () => {
    open(QUIZ)
    fireEvent.change(screen.getByLabelText('Testo della domanda'), { target: { value: 'Quale pH definisce acidosi?' } })
    fireEvent.change(screen.getByLabelText('Alternativa B'), { target: { value: 'pH oltre 7.45' } })
    fireEvent.click(screen.getByLabelText('La 2ª alternativa è quella giusta'))
    fireEvent.click(screen.getByTestId('question-edit-save'))

    expect(mockEdit).toHaveBeenCalledWith(expect.objectContaining({
      questionId: 'q1',
      body: {
        question_text: 'Quale pH definisce acidosi?',
        options: ['pH < 7.35', 'pH oltre 7.45', 'pH 7.40', 'pH 7.42'],
        correct_index: 1,
        explanation: 'Sotto 7.35 il sangue è acido.',
      },
    }), expect.anything())
  })

  it('quiz: il commento si può far riscrivere all’IA', () => {
    open(QUIZ)
    fireEvent.click(screen.getByTestId('question-edit-regenerate'))
    expect(mockRegenerate).toHaveBeenCalledWith('q1', expect.anything())
  })

  it('mirata: solo il testo, senza alternative né commento', () => {
    open(MIRATA)
    expect(screen.queryByLabelText('Alternativa A')).toBeNull()
    expect(screen.queryByTestId('question-edit-regenerate')).toBeNull()
    fireEvent.click(screen.getByTestId('question-edit-save'))
    expect(mockEdit).toHaveBeenCalledWith(expect.objectContaining({
      questionId: 'q2',
      body: { question_text: 'Spiega il gap anionico.', options: null, correct_index: null, explanation: null },
    }), expect.anything())
  })

  it('non si salva un quiz con alternative vuote o doppie', () => {
    open(QUIZ)
    fireEvent.change(screen.getByLabelText('Alternativa C'), { target: { value: '  ' } })
    expect(screen.getByTestId('question-edit-save')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Alternativa C'), { target: { value: 'pH < 7.35' } })
    expect(screen.getByTestId('question-edit-save')).toBeDisabled()
  })
})
