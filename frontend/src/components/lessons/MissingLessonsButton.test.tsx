import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { MissingLessonsButton } from './MissingLessonsButton'

const state = vi.hoisted(() => ({ enabled: true, subjects: [] as unknown[] }))
vi.mock('@/lib/preferences', () => ({ usePreference: () => [state.enabled, vi.fn()] }))
vi.mock('@/api/calendar', () => ({ useMissingLessons: () => ({ data: { subjects: state.subjects } }) }))

beforeEach(() => {
  state.enabled = true
  state.subjects = []
})

function draw(props = { materia: 'Data Mining' }) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <MissingLessonsButton {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

it('mostra date e link al blocco della settimana cliccando sul triangolo', () => {
  state.subjects = [
    {
      materia: 'DATA MINING',
      missing: [
        {
          key: 'tpl_7',
          date: '2026-10-12',
          day_name: 'Lun',
          day_number: 12,
          month_number: 10,
          start_time: '09:00',
          end_time: '11:00',
        },
      ],
    },
  ]
  draw()
  const btn = screen.getByRole('button', { name: '1 lezioni mancanti' })
  act(() => {
    fireEvent.click(btn)
  })
  expect(screen.getByTestId('missing-lessons-popup')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Lun 12\/10/ })).toHaveAttribute(
    'href',
    '/calendario?data=2026-10-12&evento=tpl_7',
  )
})

it('apre il popup al passaggio del mouse (hover)', () => {
  state.subjects = [
    {
      materia: 'DATA MINING',
      missing: [
        {
          key: 'tpl_8',
          date: '2026-10-13',
          day_name: 'Mar',
          day_number: 13,
          month_number: 10,
          start_time: '10:00',
          end_time: '11:00',
        },
      ],
    },
  ]
  draw()
  expect(screen.queryByTestId('missing-lessons-popup')).toBeNull()

  const container = screen.getByTestId('missing-lessons-button').parentElement!
  act(() => {
    fireEvent.pointerEnter(container)
  })
  expect(screen.getByTestId('missing-lessons-popup')).toBeInTheDocument()
})

it('supporta altri raggruppamenti (es. data)', () => {
  state.subjects = [
    {
      materia: 'DATA MINING',
      missing: [
        {
          key: 'tpl_9',
          date: '2026-10-15',
          day_name: 'Gio',
          day_number: 15,
          month_number: 10,
          start_time: '09:00',
          end_time: '10:00',
        },
      ],
    },
  ]
  draw({ grouping: 'data', groupKey: '2026-10-15' } as never)
  expect(screen.getByRole('button', { name: '1 lezioni mancanti' })).toBeInTheDocument()
})

it('nasconde l’avviso senza mancanti', () => {
  draw()
  expect(screen.queryByRole('button')).toBeNull()
})

it('nasconde l’avviso con la preferenza spenta', () => {
  state.enabled = false
  state.subjects = [{ materia: 'DATA MINING', missing: [{}] }]
  draw()
  expect(screen.queryByRole('button')).toBeNull()
})
