import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'

import type { Lesson } from '@/lib/format'
import { groupLessons, sortLessons, useLessonViewPrefs } from '@/lib/lessonView'
import { LessonList, LessonViewControls } from './LessonList'

const LESSONS = [
  { id: 1, materia: 'ANATOMIA', data: '2026-09-26', titolo: 'Arti superiori', folder_name: 'a', argomenti: '', phases: { build: 'VALID' }, pending_issues: 2, cost_usd: 0.3 },
  { id: 2, materia: 'FISIOLOGIA', data: '2026-09-12', titolo: 'Il rene', folder_name: 'b', argomenti: '', phases: {}, pending_issues: 0, cost_usd: 0.1 },
  { id: 3, materia: 'ANATOMIA', data: '2026-08-02', titolo: 'Cranio', folder_name: 'c', argomenti: '', phases: {}, pending_issues: 0 },
] as unknown as Lesson[]

function Page() {
  const { prefs, update, sortBy, toggleGroup } = useLessonViewPrefs()
  const groups = groupLessons(sortLessons(LESSONS, prefs.sort, prefs.dir), prefs.group, prefs.sort === 'data' ? prefs.dir : 'desc')
  return (
    <>
      <LessonViewControls shown={3} total={3} filtered={false} onReset={() => {}} prefs={prefs} onChange={update} />
      <LessonList groups={groups} grouped={prefs.group !== 'nessuno'} prefs={prefs} onSort={sortBy} onToggleGroup={toggleGroup} />
    </>
  )
}

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Page />
      </MemoryRouter>
    </QueryClientProvider>,
  )

const titles = (testId: string) => screen.getAllByTestId(testId).map((el) => within(el).getAllByRole('link').find((a) => /^\/lezioni\/\d+$/.test(a.getAttribute('href') ?? ''))?.textContent)

beforeEach(() => localStorage.clear())

describe('LessonList', () => {
  it('schede per data, poi tabella ordinabile dalle intestazioni; la vista resta salvata', async () => {
    const user = userEvent.setup()
    const { unmount } = renderPage()
    expect(titles('lesson-card')).toEqual(['Arti superiori', 'Il rene', 'Cranio'])

    await user.click(screen.getByRole('button', { name: 'Tabella' }))
    expect(screen.getByRole('button', { name: 'Tabella' })).toHaveAttribute('aria-pressed', 'true')
    expect(titles('lesson-row')).toEqual(['Arti superiori', 'Il rene', 'Cranio'])

    await user.click(screen.getByRole('button', { name: 'Titolo' }))
    expect(titles('lesson-row')).toEqual(['Arti superiori', 'Cranio', 'Il rene'])
    expect(screen.getByRole('columnheader', { name: /Titolo/ })).toHaveAttribute('aria-sort', 'ascending')
    await user.click(screen.getByRole('button', { name: 'Titolo' }))
    expect(titles('lesson-row')).toEqual(['Il rene', 'Cranio', 'Arti superiori'])

    unmount()
    renderPage()
    expect(screen.getAllByTestId('lesson-row')).toHaveLength(3)
    expect(screen.getByLabelText('Ordina per')).toHaveValue('titolo')
  })

  it('raggruppa per materia e chiude un gruppo', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.selectOptions(screen.getByLabelText('Raggruppa per'), 'materia')
    const toggles = screen.getAllByTestId('lesson-group-toggle')
    expect(toggles.map((t) => t.textContent)).toEqual(['ANATOMIA2 lezioni', 'FISIOLOGIA1 lezione'])
    expect(screen.getAllByTestId('lesson-card')).toHaveLength(3)
    await user.click(toggles[0])
    expect(toggles[0]).toHaveAttribute('aria-expanded', 'false')
    expect(titles('lesson-card')).toEqual(['Il rene'])
  })
})
