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
  it('per data: gruppi per giorno, sotto il titolo materia, docente e unità; clic sulla riga apre la lezione', () => {
    renderDashboard()
    expect(screen.getByRole('heading', { level: 1, name: 'Lezioni' })).toBeInTheDocument()
    expect(screen.getAllByTestId('lesson-group')).toHaveLength(2)
    const sub = within(row(1)).getByTestId('lesson-subtitle')
    expect(sub).toHaveTextContent('Patologia · Maria Rossi · 7 unità')
    expect(sub.className).toContain('block')
    expect(sub.className).not.toContain('max-md')
    expect(row(1).textContent).not.toMatch(/Infiammazione · Patologia/)
    expect(within(row(2)).getByTestId('lesson-subtitle')).toHaveTextContent(/^Biochimica$/)
    // Nessuna icona di azione sulle righe (Info, Recall, Studio, Apri): si apre con un clic sulla riga.
    expect(within(row(1)).getByRole('link', { name: /Infiammazione/ })).toHaveAttribute('href', '/lezioni/1')
    expect(within(row(2)).getByRole('link', { name: /Lipidi/ })).toHaveAttribute('href', '/lezioni/2')
    const names = Array.from(row(1).querySelectorAll('button, a')).map((el) => el.getAttribute('aria-label')).filter((n): n is string => Boolean(n))
    expect(names.filter((n) => ['Info', 'Recall', 'Studio', 'Apri'].includes(n))).toEqual([])
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

  it('ogni gruppo ha uno sfondo a rotazione dai colori del tema', () => {
    renderDashboard()
    const groupElements = screen.getAllByTestId('lesson-group')
    expect(groupElements).toHaveLength(2)
    expect(groupElements[0].getAttribute('style')).toContain('var(--group-1)')
    expect(groupElements[1].getAttribute('style')).toContain('var(--group-2)')
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
    expect(within(bar).getByRole('button', { name: 'Scarica Markdown' })).not.toHaveAttribute('aria-disabled')
    expect(within(bar).getByRole('button', { name: 'Scarica zip' })).not.toHaveAttribute('aria-disabled')
    // Recall sulla selezione: solo le lezioni con la rielaborazione
    expect(within(bar).getByRole('link', { name: 'Recall sulle lezioni selezionate' })).toHaveAttribute('href', '/recall/selezione/1')

    fireEvent.click(within(row(2)).getByRole('checkbox'))
    expect(within(today).getByRole('checkbox', { name: /^Seleziona il gruppo/ })).toHaveProperty('indeterminate', true)
    fireEvent.click(within(bar).getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByTestId('selection-bar')).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('la barra seleziona tutte le lezioni visibili e poi le deseleziona', () => {
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Seleziona' }))
    fireEvent.click(screen.getByRole('button', { name: 'Seleziona tutto' }))
    for (const id of [1, 2, 3]) expect(within(row(id)).getByRole('checkbox')).toBeChecked()
    expect(screen.getByTestId('selection-count')).toHaveTextContent('3 selezionate')
    fireEvent.click(screen.getByRole('button', { name: 'Deseleziona tutto' }))
    for (const id of [1, 2, 3]) expect(within(row(id)).getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByTestId('selection-count')).toHaveTextContent('0 selezionate')
    expect(screen.getByRole('button', { name: 'Seleziona tutto' })).toBeInTheDocument()
  })

  it('seleziona e deseleziona solo i risultati della ricerca, conservando le selezioni nascoste', () => {
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Seleziona' }))
    fireEvent.click(within(row(2)).getByRole('checkbox'))
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'rossi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Seleziona tutto' }))
    expect(screen.getByTestId('selection-count')).toHaveTextContent('2 selezionate')
    for (const id of [1, 3]) expect(within(row(id)).getByRole('checkbox')).toBeChecked()
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '' } })
    expect(screen.getByTestId('selection-count')).toHaveTextContent('3 selezionate')
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'rossi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Deseleziona tutto' }))
    expect(screen.getByTestId('selection-count')).toHaveTextContent('0 selezionate')
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '' } })
    expect(within(row(2)).getByRole('checkbox')).toBeChecked()
    for (const id of [1, 3]) expect(within(row(id)).getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByTestId('selection-count')).toHaveTextContent('1 selezionata')
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'zzz' } })
    const selectAll = screen.getByRole('button', { name: 'Seleziona tutto' })
    expect(selectAll).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(selectAll)
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '' } })
    expect(within(row(2)).getByRole('checkbox')).toBeChecked()
    expect(screen.getByTestId('selection-count')).toHaveTextContent('1 selezionata')
  })

  it('desktop: secondo clic su "Per data" alterna giorno e mese; clic su materia e poi di nuovo sul calendario torna all\'ultima scelta', () => {
    renderDashboard()
    const dateBtn = screen.getByRole('button', { name: 'Per data' })
    expect(dateBtn).toHaveAttribute('aria-pressed', 'true')

    // Secondo clic su Per data -> passa a Per mese
    fireEvent.click(dateBtn)
    const monthBtn = screen.getByRole('button', { name: 'Per mese' })
    expect(monthBtn).toHaveAttribute('aria-pressed', 'true')
    expect(JSON.parse(localStorage.getItem('rt-lessons-page')!)).toMatchObject({ group: 'mese' })

    // Nel raggruppamento per mese il sottotitolo mostra anche la data
    expect(within(row(1)).getByTestId('lesson-subtitle')).toHaveTextContent('28 set · Patologia · Maria Rossi · 7 unità')

    // Terzo clic -> torna a Per data
    fireEvent.click(monthBtn)
    expect(screen.getByRole('button', { name: 'Per data' })).toHaveAttribute('aria-pressed', 'true')
    expect(JSON.parse(localStorage.getItem('rt-lessons-page')!)).toMatchObject({ group: 'data' })

    // Clic su Per data -> Per mese, poi Clic su Per materia
    fireEvent.click(screen.getByRole('button', { name: 'Per data' }))
    expect(screen.getByRole('button', { name: 'Per mese' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(screen.getByRole('button', { name: 'Per materia' })).toHaveAttribute('aria-pressed', 'true')
    const inactiveMonthBtn = screen.getByRole('button', { name: 'Per mese' })
    expect(inactiveMonthBtn).toHaveAttribute('aria-pressed', 'false')

    // Clic sul pulsante calendario: torna a Per mese
    fireEvent.click(inactiveMonthBtn)
    expect(screen.getByRole('button', { name: 'Per mese' })).toHaveAttribute('aria-pressed', 'true')
    expect(JSON.parse(localStorage.getItem('rt-lessons-page')!)).toMatchObject({ group: 'mese' })
  })

  it('su telefono: i pulsanti raggruppa e ordina passano al valore successivo a ogni tocco', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('767.98px'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    renderDashboard()
    const groupBtn = screen.getByRole('button', { name: /Raggruppa: Data/ })
    expect(groupBtn).toBeInTheDocument()
    fireEvent.click(groupBtn)
    expect(screen.getByRole('button', { name: /Raggruppa: Mese/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Raggruppa: Mese/ }))
    expect(screen.getByRole('button', { name: /Raggruppa: Materia/ })).toBeInTheDocument()
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
    fireEvent.click(screen.getByRole('button', { name: /Raggruppa: Materia/ }))
    expect(screen.getByRole('button', { name: /Raggruppa: Docente/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Raggruppa: Docente/ }))
    expect(screen.getByRole('button', { name: /Raggruppa: Data/ })).toBeInTheDocument()

    const sortBtn = screen.getByRole('button', { name: /Ordina: Recenti/ })
    expect(sortBtn).toBeInTheDocument()
    fireEvent.click(sortBtn)
    expect(screen.getByRole('button', { name: /Ordina: Vecchie/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Vecchie/ }))
    expect(screen.getByRole('button', { name: /Ordina: A–Z/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: A–Z/ }))
    expect(screen.getByRole('button', { name: /Ordina: Studio/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Studio/ }))
    expect(screen.getByRole('button', { name: /Ordina: Avanti/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Avanti/ }))
    expect(screen.getByRole('button', { name: /Ordina: Indietro/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Indietro/ }))
    expect(screen.getByRole('button', { name: /Ordina: Recenti/ })).toBeInTheDocument()
  })
})
