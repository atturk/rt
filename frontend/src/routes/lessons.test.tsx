import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { DashboardPage } from './lessons'

const LESSONS = [
  {
    id: 1, materia: 'PATOLOGIA', data: '2026-09-28', titolo: 'Infiammazione', folder_name: 'a', argomenti: '', docente: 'Maria Rossi', path: '',
    phases: { build: 'VALID', rewrite: 'VALID' }, pending_issues: 2, unit_count: 7, duration_seconds: 3120, recall_questions: 38, recall_pending: 14, cost_usd: 0.42,
    state: 'completato',
  },
  {
    id: 2, materia: 'BIOCHIMICA', data: '2026-09-28', titolo: 'Lipidi', folder_name: 'b', argomenti: '', docente: '', path: '',
    phases: { build: 'STALE', rewrite: 'MISSING' }, pending_issues: 0, unit_count: null, recall_questions: 0, recall_pending: 0,
  },
  {
    id: 3, materia: 'PATOLOGIA', data: '2026-09-05', titolo: 'Shock', folder_name: 'c', argomenti: '', docente: 'Maria Rossi', path: '',
    phases: { build: 'VALID', rewrite: 'VALID' }, pending_issues: 0, unit_count: 4, recall_questions: 0, recall_pending: 0,
  },
]

vi.mock('@/api/hooks', () => ({
  useLessons: () => ({ isPending: false, isError: false, data: LESSONS }),
  useLesson: () => ({ isPending: true }),
  useLessonDocument: () => ({ data: undefined }),
}))
vi.mock('@/api/jobs', () => ({
  useJobs: () => ({ data: [{ id: 'j1', state: 'running', lesson_id: 3 }] }),
  useJob: () => ({ data: undefined }),
}))
vi.mock('@/components/lesson/DocumentView', () => ({ DocumentView: () => null }))
vi.mock('@/components/lesson/AudioPlayer', () => ({ AudioPlayer: () => null }))

function renderDashboard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const row = (id: number) => document.querySelector<HTMLElement>(`[data-testid=lesson-row][data-lesson-id="${id}"]`)!
const groups = () => screen.getAllByTestId('lesson-group').map((g) => within(g).getByRole('heading').textContent)

beforeEach(() => localStorage.clear())

describe('pagina Lezioni', () => {
  it('per data: gruppi per giorno, sotto il titolo materia, docente e unità', () => {
    renderDashboard()
    expect(screen.getByRole('heading', { level: 1, name: 'Lezioni' })).toBeInTheDocument()
    expect(screen.getAllByTestId('lesson-group')).toHaveLength(2)
    expect(within(row(1)).getByTestId('lesson-subtitle')).toHaveTextContent('Patologia · Maria Rossi · 7 unità')
    expect(within(row(2)).getByTestId('lesson-subtitle')).toHaveTextContent(/^Biochimica$/)
    // Azioni sempre nello stesso ordine: Info, Recall, Studio, Apri.
    const names = Array.from(row(1).querySelectorAll('button, a')).map((el) => el.getAttribute('aria-label')).filter(Boolean)
    expect(names).toEqual(['Info', 'Recall', 'Studio', 'Apri'])
    expect(within(row(1)).getByRole('link', { name: 'Recall' })).toHaveAttribute('href', '/lezioni/1/recall')
    expect(within(row(1)).getByRole('link', { name: 'Studio' })).toHaveAttribute('href', '/studio/lezione/1')
    // Senza rielaborazione Recall e Studio restano al loro posto, non disponibili.
    expect(within(row(2)).getByRole('button', { name: 'Recall' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('il pallino dice lo stato: in corso, da verificare', () => {
    renderDashboard()
    expect(within(row(3)).getByTestId('lesson-status')).toHaveAttribute('data-status', 'in-corso')
    expect(within(row(1)).getByTestId('lesson-status')).toHaveAttribute('data-status', 'da-verificare')
  })

  it('per materia e per docente: il sottotitolo cambia; il gruppo non ha più Recall né Studio (si seleziona)', () => {
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(screen.getByRole('button', { name: 'Per materia' })).toHaveAttribute('aria-pressed', 'true')
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
    expect(within(row(1)).getByTestId('lesson-subtitle')).toHaveTextContent('28 set · Maria Rossi · 7 unità')
    const patologia = screen.getAllByTestId('lesson-group')[1]
    expect(within(patologia).queryByRole('link', { name: /su tutto il gruppo/ })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Per docente' }))
    expect(groups()).toEqual(['Maria Rossi', 'Senza docente'])
    expect(within(row(3)).getByTestId('lesson-subtitle')).toHaveTextContent('5 set · Patologia · 4 unità')
    // La scelta resta nel browser.
    expect(JSON.parse(localStorage.getItem('rt-lessons-page')!)).toMatchObject({ group: 'docente' })
  })

  it('la ricerca filtra le righe', () => {
    renderDashboard()
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'rossi' } })
    expect(screen.getAllByTestId('lesson-row')).toHaveLength(2)
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'zzz' } })
    expect(screen.getByTestId('lessons-empty')).toHaveTextContent('Nessuna lezione corrisponde alla ricerca.')
  })

  it('Info: popup con tutti i campi elisi dalla riga, si chiude con la X', () => {
    renderDashboard()
    fireEvent.click(within(row(1)).getByRole('button', { name: 'Info' }))
    const info = screen.getByTestId('lesson-info')
    expect(within(info).getByRole('heading', { name: 'Infiammazione' })).toBeInTheDocument()
    const values = Object.fromEntries(
      within(info).getAllByRole('term').map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]),
    )
    expect(values).toMatchObject({ Materia: 'Patologia', Durata: '52 min', Unità: '7', Domande: '38 nel pool · 14 da fare', Costo: '$0.42' })
    expect(values.Stato).toBe('completata · 2 da verificare')
    fireEvent.click(within(info).getByRole('button', { name: 'Chiudi' }))
    expect(within(info).queryByRole('term')).toBeNull()
  })

  it('selezione: la casella del gruppo prende tutto il gruppo, la barra scarica Markdown e zip', () => {
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Seleziona' }))
    const [today] = screen.getAllByTestId('lesson-group')
    fireEvent.click(within(today).getByRole('checkbox', { name: /^Seleziona il gruppo/ }))
    expect(within(row(1)).getByRole('checkbox')).toBeChecked()
    expect(within(row(2)).getByRole('checkbox')).toBeChecked()
    const bar = screen.getByTestId('selection-bar')
    expect(within(bar).getByTestId('selection-count')).toHaveTextContent('2 selezionate')
    // Markdown solo delle lezioni con il documento finale; zip di tutte.
    expect(within(bar).getByRole('link', { name: 'Scarica Markdown' })).toHaveAttribute('href', '/api/v1/lesson-exports?ids=1&format=markdown&name=Lezioni+selezionate')
    expect(within(bar).getByRole('link', { name: 'Scarica zip' })).toHaveAttribute('href', '/api/v1/lesson-exports?ids=1&ids=2&format=zip&name=Lezioni+selezionate')
    // Recall sulla selezione: solo le lezioni con la rielaborazione
    expect(within(bar).getByRole('link', { name: 'Recall sulle lezioni selezionate' })).toHaveAttribute('href', '/recall/selezione/1')

    fireEvent.click(within(row(2)).getByRole('checkbox'))
    expect(within(today).getByRole('checkbox', { name: /^Seleziona il gruppo/ })).toHaveProperty('indeterminate', true)
    fireEvent.click(within(bar).getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByTestId('selection-bar')).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })
})
