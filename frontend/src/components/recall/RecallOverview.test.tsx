import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { RecallOverviewPage } from './RecallOverview'

const LESSONS = [
  { id: 1, materia: 'BIOCHIMICA', data: '2026-09-05', titolo: 'Lipidi', folder_name: 'a', argomenti: '', path: '', phases: { rewrite: 'VALID' }, pending_issues: 0 },
  { id: 2, materia: 'BIOCHIMICA', data: '2026-09-06', titolo: 'Proteine', folder_name: 'b', argomenti: '', path: '', phases: {}, pending_issues: 0 },
  { id: 3, materia: 'FISIOLOGIA', data: '2026-09-07', titolo: 'Rene', folder_name: 'c', argomenti: '', path: '', phases: { rewrite: 'VALID' }, pending_issues: 0 },
]
const SUBJECTS = [
  { materia: 'BIOCHIMICA', session: { id: 9 }, lessons: [
    { lesson_id: 1, ready: true, questions: { quiz: { pending: 4, answered: 1 }, mirata: { pending: 2 } }, answers: 1, telegram: false },
    { lesson_id: 2, ready: false, questions: {}, answers: 0, telegram: false },
  ] },
  { materia: 'FISIOLOGIA', session: null, lessons: [{ lesson_id: 3, ready: true, questions: {}, answers: 0, telegram: true }] },
]

vi.mock('@/api/hooks', () => ({ useLessons: () => ({ isPending: false, isError: false, data: LESSONS }) }))
vi.mock('@/api/recall', () => ({ useSubjectsRecall: () => ({ isPending: false, isError: false, data: SUBJECTS }) }))

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/recall']}>
        <RecallOverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const subject = (name: string) => document.querySelector<HTMLElement>(`[data-testid=recall-subject][data-subject="${name}"]`)!

describe('pagina Recall', () => {
  beforeEach(() => localStorage.clear())

  it('mostra le lezioni per materia con il pool e il recall della materia', () => {
    renderPage()
    const bio = subject('BIOCHIMICA')
    expect(within(bio).getByTestId('subject-pending')).toHaveTextContent('6 domande da porre')
    expect(within(bio).getByText('Sessione in corso')).toBeInTheDocument()
    expect(within(bio).getByTestId('subject-recall')).toHaveAttribute('href', '/recall/materie/BIOCHIMICA')
    expect(within(bio).getByRole('link', { name: 'Lipidi' })).toHaveAttribute('href', '/lezioni/1/recall')
    expect(within(bio).queryByRole('link', { name: 'Proteine' })).toBeNull()
    expect(within(bio).getByText(/serve prima la rielaborazione/)).toBeInTheDocument()
    expect(within(subject('FISIOLOGIA')).getByText('Telegram')).toBeInTheDocument()
  })

  it('passa alla tabella e chiude una materia, ricordandolo', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Tabella' }))
    expect(screen.getByTestId('recall-table')).toBeInTheDocument()
    const row = document.querySelector('[data-testid=picker-lesson][data-lesson-id="1"]')!
    expect(Array.from(row.querySelectorAll('td')).map((td) => td.textContent)).toEqual(['Lipidi', '2026-09-05', '4', '2', '0', '1'])
    fireEvent.click(within(subject('FISIOLOGIA')).getByTestId('lesson-group-toggle'))
    expect(document.querySelector('[data-testid=picker-lesson][data-lesson-id="3"]')).toBeNull()
    expect(JSON.parse(localStorage.getItem('rt-recall-view')!)).toMatchObject({ view: 'tabella', collapsed: ['materia:FISIOLOGIA'] })
  })
})
