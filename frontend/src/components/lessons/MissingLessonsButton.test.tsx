import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { MissingLessonsButton } from './MissingLessonsButton'

const state = vi.hoisted(() => ({ enabled: true, subjects: [] as unknown[] }))
vi.mock('@/lib/preferences', () => ({ usePreference: () => [state.enabled, vi.fn()] }))
vi.mock('@/api/calendar', () => ({ useMissingLessons: () => ({ data: { subjects: state.subjects } }) }))
beforeEach(() => { state.enabled = true; state.subjects = [] })
function draw() { render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><MissingLessonsButton materia="Data Mining" /></MemoryRouter></QueryClientProvider>) }
it('mostra date e link al blocco della settimana', () => {
  state.subjects = [{ materia: 'DATA MINING', missing: [{ key: 'tpl_7', date: '2026-10-12', day_name: 'Lun', day_number: 12, month_number: 10, start_time: '09:00', end_time: '11:00' }] }]
  draw()
  fireEvent.click(screen.getByRole('button', { name: '1 lezioni mancanti' }))
  expect(screen.getByRole('link', { name: /Lun 12\/10/ })).toHaveAttribute('href', '/calendario?data=2026-10-12&evento=tpl_7')
})
it('nasconde l’avviso senza mancanti', () => { draw(); expect(screen.queryByRole('button')).toBeNull() })
it('nasconde l’avviso con la preferenza spenta', () => {
  state.enabled = false
  state.subjects = [{ materia: 'DATA MINING', missing: [{}] }]
  draw(); expect(screen.queryByRole('button')).toBeNull()
})
