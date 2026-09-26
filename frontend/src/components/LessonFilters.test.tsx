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

  it('il punto interrogativo spiega cosa si cerca, al focus da tastiera', async () => {
    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const help = screen.getByRole('button', { name: 'Informazioni sul filtro di testo' })
    expect(screen.getByLabelText('Cerca')).toHaveAttribute('placeholder', 'Titolo, argomenti, materia o data')
    await user.tab()
    expect(help).toHaveFocus()
    expect(help).toHaveAccessibleDescription(/titolo.*argomenti.*materia.*data/i)
    expect(screen.getByRole('tooltip')).toBeVisible()
    await user.hover(help)
    expect(screen.getByRole('tooltip')).toBeVisible()
  })
})
