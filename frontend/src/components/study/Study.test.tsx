import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { StudyFlow } from './Study'
import type { Lesson } from '@/lib/format'

const LESSON: Lesson = {
  id: 1,
  materia: 'FISIOLOGIA',
  titolo: 'Emogasanalisi e acidosi',
  data: '2026-10-02',
  folder_name: 'a',
  phases: { build: 'VALID', rewrite: 'VALID' },
  argomenti: '',
  docente: 'Rossi',
  path: '',
  duration_seconds: 3600,
  unit_count: 3,
  pending_issues: 0,
  recall_pending: 0,
  recall_questions: 3,
}

const UNITS = [
  { id: '1.1', title: 'Continuità didattica', html: '<p>Contenuto 1</p>', questions: 2, pending: {} },
  { id: '1.2', title: 'Acidosi metabolica', html: '<p>Contenuto 2</p>', questions: 1, pending: {} },
  { id: '2.1', title: 'Prelievo arterioso', html: '<p>Contenuto 3</p>', questions: 0, pending: {} },
]

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useStudyLesson: () => ({
      data: { id: 1, units: UNITS, has_audio: false },
      isPending: false,
      isError: false,
    }),
  }
})

function renderStudy() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StudyFlow unit navigation', () => {
  it('mostra il pulsante Unità 1 di 3 e apre l\'indice per navigare all\'unità 1.2', () => {
    renderStudy()
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Continuità didattica' })).toBeInTheDocument()
    const toggle = screen.getByTestId('unit-index-toggle')
    expect(toggle).toHaveTextContent('Unità 1 di 3')

    // Apri l'indice
    fireEvent.click(toggle)
    const menu = screen.getByTestId('unit-index-menu')
    expect(menu).toBeInTheDocument()
    expect(menu).toHaveTextContent('Sezione 1')
    expect(menu).toHaveTextContent('Sezione 2')

    // Clicca sull'unità 1.2
    const unit12Btn = screen.getByRole('menuitem', { name: /1.2 Acidosi metabolica/ })
    fireEvent.click(unit12Btn)

    // L'unità mostrata passa a 1.2
    expect(screen.getByRole('heading', { level: 2, name: '1.2 Acidosi metabolica' })).toBeInTheDocument()
    expect(screen.getByTestId('unit-index-toggle')).toHaveTextContent('Unità 2 di 3')
  })
})
