import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { vi } from 'vitest'

import { DashboardPage } from './lessons'

const LESSONS = [
  { id: 1, materia: 'PATOLOGIA GENERALE 2', data: '2026-09-28', titolo: 'Infiammazione', folder_name: 'a', argomenti: '', path: '', phases: { build: 'VALID' }, pending_issues: 0 },
  { id: 2, materia: 'BIOCHIMICA', data: '2026-09-05', titolo: 'Lipidi', folder_name: 'b', argomenti: '', path: '', phases: { build: 'STALE' }, pending_issues: 0 },
]

vi.mock('@/api/hooks', () => ({
  useLessons: () => ({ isPending: false, isError: false, data: LESSONS }),
  useLesson: () => ({ isPending: true }),
  useLessonDocument: () => ({ data: undefined }),
}))
vi.mock('@/components/lesson/DocumentView', () => ({ DocumentView: () => null }))
vi.mock('@/components/lesson/AudioPlayer', () => ({ AudioPlayer: () => null }))

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderDashboard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const card = (id: number) => document.querySelector<HTMLElement>(`[data-testid=lesson-card][data-lesson-id="${id}"]`)!

describe('scheda della lezione con Option', () => {
  it('sotto il cestino il download del Markdown finale, solo con build valido', () => {
    renderDashboard()
    const link = within(card(1)).getByRole('link', { name: 'Scarica il Markdown di Infiammazione' })
    expect(link).toHaveAttribute('href', '/api/v1/lessons/1/export?format=markdown')
    expect(link).toHaveAttribute('download')
    expect(within(card(2)).queryByRole('link', { name: /Scarica il Markdown/ })).toBeNull()

    const trash = within(card(1)).getByRole('button', { name: /^Elimina/ })
    expect(link.className).toContain('md:opacity-0')
    expect(trash.className).toContain('md:opacity-0')
    fireEvent.keyDown(window, { key: 'Alt' })
    expect(link.className).not.toContain('md:opacity-0')
    expect(trash.className).not.toContain('md:opacity-0')
    fireEvent.keyUp(window, { key: 'Alt' })
    expect(link.className).toContain('md:opacity-0')
  })

  it('il download non apre la lezione', () => {
    renderDashboard()
    fireEvent.click(within(card(1)).getByRole('link', { name: /Scarica il Markdown/ }))
    expect(screen.getByTestId('where').textContent).toBe('/')
  })
})
