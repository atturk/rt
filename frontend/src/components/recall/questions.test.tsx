import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { QuestionsPage } from './QuestionsPage'

const mutate = vi.fn()
const reveals: boolean[] = []
const question = (id: string, type: string, status = 'pending') => ({
  id, type, status, unit_ids: ['1.1'], question_text: `Domanda ${id}`, options: type === 'quiz' ? ['A', 'B', 'C', 'D'] : null,
  correct_index: null, explanation: null, created_at: '2026-09-30T20:00:00', classifier_level: 2, vote: null,
})
const QUESTIONS = [question('q1', 'quiz'), question('q2', 'mirata'), question('q3', 'mirata', 'answered'), question('q4', 'vasta')]

vi.mock('@/api/hooks', () => ({ useLesson: () => ({ data: { titolo: 'Infiammazione', materia: 'PATOLOGIA', data: '2026-09-30' } }) }))
vi.mock('@/api/recall', () => ({
  useRecallQuestions: (_id: number, reveal: boolean) => {
    reveals.push(reveal)
    return { isPending: false, isError: false, isSuccess: true, data: { questions: QUESTIONS, unit_titles: { '1.1': 'Mediatori' } } }
  },
  useDeleteQuestions: () => ({ mutate, isPending: false, isError: false, isSuccess: false }),
}))

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
beforeEach(() => mutate.mockReset())

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/lezioni/7/recall/domande']}>
      <Routes>
        <Route path="/lezioni/:lessonId/recall/domande" element={<QuestionsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const box = (id: string) => within(document.querySelector<HTMLElement>(`[data-question-id=${id}]`)!).getByRole('checkbox')

describe('domande della lezione', () => {
  it('elenca le domande con unità e filtra per tipo', () => {
    renderPage()
    expect(screen.getAllByTestId('question-item')).toHaveLength(4)
    expect(screen.getAllByText('1.1 Mediatori')).toHaveLength(4)
    fireEvent.change(screen.getByLabelText('Tipo'), { target: { value: 'mirata' } })
    expect(screen.getAllByTestId('question-item').map((li) => li.dataset.questionId)).toEqual(['q2', 'q3'])
    expect(screen.getByTestId('questions-count')).toHaveTextContent('2 di 4 domande')
  })

  it('le soluzioni si chiedono solo spuntando Mostra le soluzioni', () => {
    renderPage()
    expect(reveals.at(-1)).toBe(false)
    fireEvent.click(screen.getByLabelText('Mostra le soluzioni'))
    expect(reveals.at(-1)).toBe(true)
  })

  it('seleziona tutte, un intervallo con Maiuscolo e chiede conferma prima di eliminare', () => {
    renderPage()
    fireEvent.click(box('q1'))
    fireEvent.click(box('q3'), { shiftKey: true })
    expect(screen.getByRole('button', { name: /Elimina selezionate \(3\)/ })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /Elimina selezionate/ }))
    expect(screen.getByText(/Una è già stata posta/)).toBeInTheDocument()
    expect(mutate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Elimina' }))
    expect(mutate.mock.calls[0][0]).toEqual(['q1', 'q2', 'q3'])
  })

  it('con un filtro elimina solo le domande mostrate', () => {
    renderPage()
    fireEvent.click(screen.getByLabelText('Seleziona tutte quelle mostrate'))
    fireEvent.change(screen.getByLabelText('Tipo'), { target: { value: 'vasta' } })
    fireEvent.click(screen.getByRole('button', { name: /Elimina selezionate \(1\)/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Elimina' }))
    expect(mutate.mock.calls[0][0]).toEqual(['q4'])
  })
})
