import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'

import type { Lesson } from '@/lib/format'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { LessonFilters } from './LessonFilters'

const LESSONS = [
  { id: 1, materia: 'ANATOMIA', data: '2026-09-26', titolo: 'Arti superiori', folder_name: 'a', argomenti: '', phases: {}, pending_issues: 0 },
  { id: 2, materia: 'FISIOLOGIA', data: '2026-09-12', titolo: 'Il rene', folder_name: 'b', argomenti: '', phases: {}, pending_issues: 0 },
] as unknown as Lesson[]

function Page() {
  const { filters, setFilter, filtered } = useFilteredLessons(LESSONS)
  return (
    <>
      <LessonFilters lessons={LESSONS} filters={filters} onChange={setFilter} />
      <ul>
        {filtered.map((l) => (
          <li key={l.id}>{l.titolo}</li>
        ))}
      </ul>
      <p data-testid="search">{useLocation().search}</p>
    </>
  )
}

describe('LessonFilters', () => {
  it('filtra sul client per testo e data, con i filtri nell’URL', async () => {
    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Cerca'), '26/09/2026')
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Arti superiori'])
    expect(screen.getByTestId('search').textContent).toContain('q=26%2F09%2F2026')
    await user.clear(screen.getByLabelText('Cerca'))
    await user.selectOptions(screen.getByLabelText('Materia'), 'FISIOLOGIA')
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Il rene'])
  })

  it('Cerca, Materia e Stato hanno la stessa struttura: etichetta sopra il campo, niente "?"', () => {
    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByLabelText('Cerca')).toHaveAttribute('placeholder', 'Titolo, materia, data…')
    const columns = ['Cerca', 'Materia', 'Stato'].map((name) => screen.getByLabelText(name).parentElement!)
    for (const column of columns) {
      expect(column.parentElement).toBe(columns[0].parentElement)
      expect(Array.from(column.children, (el) => el.tagName)).toEqual(['LABEL', expect.stringMatching(/^(INPUT|SELECT)$/)])
    }
  })
})
