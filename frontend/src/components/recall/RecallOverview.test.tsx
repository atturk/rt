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
    { lesson_id: 1, ready: true, questions: { quiz: { pending: 4, answered: 1 }, mirata: { pending: 2 } }, answers: 1, telegram: false,
      classification: { state: 'never', classified: 0, total: 3 } },
    { lesson_id: 2, ready: false, questions: {}, answers: 0, telegram: false },
  ] },
  { materia: 'FISIOLOGIA', session: null, lessons: [{ lesson_id: 3, ready: true, questions: {}, answers: 0, telegram: true,
    classification: { state: 'done', classified: 2, total: 2 } }] },
  { materia: 'GIORNO:2026-09-07', session: { id: 11 }, lessons: [] },
]

vi.mock('@/api/hooks', () => ({ useLessons: () => ({ isPending: false, isError: false, data: LESSONS }) }))
const queued = vi.hoisted(() => ({ classify: vi.fn(), pool: vi.fn() }))
vi.mock('@/api/recall', () => ({
  useSubjectsRecall: () => ({ isPending: false, isError: false, data: SUBJECTS }),
  useQueueForLessons: (kind: 'classify' | 'pool') => ({ mutate: queued[kind], isPending: false, isError: false, data: undefined }),
}))

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
  beforeEach(() => { localStorage.clear(); queued.classify.mockReset(); queued.pool.mockReset() })

  it('nella barra del gruppo classifica tutte e rigenera i pool delle lezioni da classificare', () => {
    renderPage()
    const bio = subject('BIOCHIMICA')
    fireEvent.click(within(bio).getByTestId('group-classify'))
    expect(queued.classify).toHaveBeenCalledWith([1])
    fireEvent.click(within(bio).getByTestId('group-pools'))
    expect(queued.pool).toHaveBeenCalledWith([1])
    // tutte classificate: niente da accodare
    expect(within(subject('FISIOLOGIA')).getByTestId('group-classify')).toBeDisabled()
    expect(within(subject('FISIOLOGIA')).getByTestId('group-pools')).toBeDisabled()
  })

  it('con Option il clic sull\'etichetta classifica subito, senza aprire il classificatore', () => {
    renderPage()
    const badge = within(subject('BIOCHIMICA')).getByTestId('classification').closest('a')!
    fireEvent.click(badge, { altKey: true })
    expect(queued.classify).toHaveBeenCalledWith([1])
  })

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
    expect(Array.from(row.querySelectorAll('td')).map((td) => td.textContent)).toEqual(['Lipidi', '2026-09-05', 'Non classificata', '4', '2', '0', '1'])
    fireEvent.click(within(subject('FISIOLOGIA')).getByTestId('lesson-group-toggle'))
    expect(document.querySelector('[data-testid=picker-lesson][data-lesson-id="3"]')).toBeNull()
    expect(JSON.parse(localStorage.getItem('rt-recall-view')!)).toMatchObject({ view: 'tabella', collapsed: ['materia:FISIOLOGIA'] })
  })

  it('raggruppa per giorno con il Recall del giorno e mostra il classificatore', () => {
    renderPage()
    expect(within(subject('BIOCHIMICA')).getByTestId('classification')).toHaveTextContent('Non classificata')
    expect(within(subject('BIOCHIMICA')).getByTestId('classification').closest('a')).toHaveAttribute('href', '/lezioni/1/rilevanza')
    expect(within(subject('FISIOLOGIA')).getByTestId('classification')).toHaveTextContent('Classificata')
    fireEvent.change(screen.getByLabelText('Raggruppa per'), { target: { value: 'giorno' } })
    const day = subject('2026-09-07')
    expect(within(day).getByTestId('subject-recall')).toHaveAttribute('href', '/recall/giorno/2026-09-07')
    expect(within(day).getByTestId('subject-recall')).toHaveTextContent('Recall del giorno')
    expect(within(day).getByText('Sessione in corso')).toBeInTheDocument()
    // giorno senza lezioni pronte: niente recall del giorno
    expect(within(subject('2026-09-06')).queryByTestId('subject-recall')).toBeNull()
    expect(JSON.parse(localStorage.getItem('rt-recall-view')!)).toMatchObject({ group: 'giorno' })
  })
})
