import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { LessonPage } from './lessons'

vi.mock('@/api/hooks', () => ({
  useLesson: () => ({ data: { id: 1, titolo: 'Acidosi', materia: 'FISIOLOGIA', data: '2026-10-02', docente: 'Rossi', unit_count: 9, duration_seconds: 4800, phases: {}, has_audio: false } }),
  useLessonDocument: () => ({ data: undefined }),
}))
vi.mock('@/api/jobs', () => ({ useJobs: () => ({ data: [] }) }))
vi.mock('@/components/jobs/JobsIndicator', () => ({ LessonWaiting: () => null }))

beforeEach(() => localStorage.clear())

it('mostra i metadati sotto il titolo e le azioni del wireframe Main', () => {
  render(<MemoryRouter initialEntries={['/lezioni/1']}><Routes><Route path="/lezioni/:lessonId" element={<LessonPage />} /></Routes></MemoryRouter>)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Acidosi')
  expect(screen.getByTestId('lesson-path')).toHaveTextContent('Fisiologia · 2 ott · Rossi')
  expect(screen.getByTestId('lesson-meta')).toHaveTextContent('9 unità · 1 h 20 min')
  expect(document.querySelector('header')).not.toHaveTextContent('Fisiologia')
  const actions = within(screen.getByTestId('lesson-actions'))
  expect(actions.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Domande', 'Studio', 'Arricchimento', 'Verifica con LLM', 'Dettagli', 'Esporta'])
  fireEvent.click(actions.getByRole('button', { name: 'Domande' }))
  expect(screen.getByRole('complementary', { name: 'Domande' })).toBeInTheDocument()
  fireEvent.click(actions.getByRole('button', { name: 'Arricchimento' }))
  expect(screen.getAllByRole('complementary')).toHaveLength(1)
  expect(screen.getByRole('complementary', { name: 'Arricchimento' })).toBeInTheDocument()
})
