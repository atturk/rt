import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { DashboardPage } from './lessons'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never

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

function renderDashboard(initialEntries: string[] = ['/']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const row = (id: number) => document.querySelector<HTMLElement>(`[data-testid=lesson-row][data-lesson-id="${id}"]`)!
const groups = () => screen.getAllByTestId('lesson-group').map((g) => within(g).getByRole('heading').textContent)

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

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
    // Esporta PDF solo delle lezioni con il documento finale; .rt di tutte.
    expect(within(bar).getByRole('button', { name: 'Esporta PDF' })).not.toHaveAttribute('aria-disabled')
    expect(within(bar).getByRole('button', { name: 'Esporta lezioni (.rt)' })).not.toHaveAttribute('aria-disabled')
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

    // Terzo clic -> passa a Senza gruppi (nessuno)
    fireEvent.click(monthBtn)
    expect(screen.getByRole('button', { name: 'Per data' })).toHaveAttribute('aria-pressed', 'false')
    expect(JSON.parse(localStorage.getItem('rt-lessons-page')!)).toMatchObject({ group: 'nessuno' })

    // Quarto clic -> torna a Per data
    fireEvent.click(screen.getByRole('button', { name: 'Per data' }))
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
    expect(screen.getByRole('button', { name: /Raggruppa: Nessuno/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Raggruppa: Nessuno/ }))
    expect(screen.getByRole('button', { name: /Raggruppa: Data/ })).toBeInTheDocument()

    const sortBtn = screen.getByRole('button', { name: /Ordina: Recenti/ })
    expect(sortBtn).toBeInTheDocument()
    fireEvent.click(sortBtn)
    expect(screen.getByRole('button', { name: /Ordina: Vecchie/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Vecchie/ }))
    expect(screen.getByRole('button', { name: /Ordina: Create/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Ordina: Create/ }))
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

  it('pin di categoria: fissa il gruppo in cima, sostituisce nello stesso raggruppamento e sgancia al secondo clic', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(undefined))
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(undefined))
    renderDashboard()

    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(groups()).toEqual(['Biochimica', 'Patologia'])

    fireEvent.click(screen.getByRole('button', { name: 'Fissa in cima Patologia' }))
    await waitFor(() => expect(groups()).toEqual(['Patologia', 'Biochimica']))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pins' } },
      body: { materia: 'PATOLOGIA' },
    }))
    expect(screen.getAllByRole('button', { name: 'Togli Patologia dalla cima' })).toHaveLength(2)

    // Fissare un'altra categoria nello stesso raggruppamento sostituisce la precedente
    fireEvent.click(screen.getByRole('button', { name: 'Fissa in cima Biochimica' }))
    await waitFor(() => expect(groups()).toEqual(['Biochimica', 'Patologia']))
    await waitFor(() => expect(put).toHaveBeenLastCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pins' } },
      body: { materia: 'BIOCHIMICA' },
    }))

    // Secondo clic sul gruppo fissato lo sgancia
    const [, groupPin] = screen.getAllByRole('button', { name: 'Togli Biochimica dalla cima' })
    fireEvent.click(groupPin)
    await waitFor(() => expect(groups()).toEqual(['Biochimica', 'Patologia']))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pins' } },
    }))
  })

  it('pin per raggruppamento indipendenti (giorno, materia, docente) con cambio vista e ritorno', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(undefined))
    renderDashboard()

    // Fissa il 5 settembre in Per data
    const [firstDateGroup, secondDateGroup] = screen.getAllByTestId('lesson-group')
    expect(firstDateGroup.getAttribute('data-group')).toBe('2026-09-28')
    expect(secondDateGroup.getAttribute('data-group')).toBe('2026-09-05')
    fireEvent.click(within(secondDateGroup).getByTestId('group-pin'))
    await waitFor(() => expect(screen.getAllByTestId('lesson-group').map((g) => g.getAttribute('data-group'))).toEqual(['2026-09-05', '2026-09-28']))

    // Cambia a Per materia: il pin della data non si vede ma resta salvato; fissa Patologia
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
    fireEvent.click(screen.getByRole('button', { name: 'Fissa in cima Patologia' }))
    await waitFor(() => expect(groups()).toEqual(['Patologia', 'Biochimica']))

    // Cambia a Per docente: fissa Senza docente
    fireEvent.click(screen.getByRole('button', { name: 'Per docente' }))
    expect(groups()).toEqual(['Maria Rossi', 'Senza docente'])
    fireEvent.click(screen.getByRole('button', { name: 'Fissa in cima Senza docente' }))
    await waitFor(() => expect(groups()).toEqual(['Senza docente', 'Maria Rossi']))

    await waitFor(() => expect(put).toHaveBeenLastCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pins' } },
      body: { data: '2026-09-05', materia: 'PATOLOGIA', docente: '' },
    }))

    // Tornando ai raggruppamenti precedenti i loro pin riappaiono
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(groups()).toEqual(['Patologia', 'Biochimica'])

    fireEvent.click(screen.getByRole('button', { name: 'Per data' }))
    expect(screen.getAllByTestId('lesson-group').map((g) => g.getAttribute('data-group'))).toEqual(['2026-09-05', '2026-09-28'])
  })

  it('ricerca che esclude il gruppo fissato: non compare ma resta salvato e torna in cima cancellata la query', () => {
    localStorage.setItem('rt-pref:lessons.pins', JSON.stringify({ materia: 'PATOLOGIA' }))
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(groups()).toEqual(['Patologia', 'Biochimica'])

    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'Lipidi' } })
    expect(groups()).toEqual(['Biochimica'])
    expect(JSON.parse(localStorage.getItem('rt-pref:lessons.pins')!)).toEqual({ materia: 'PATOLOGIA' })

    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '' } })
    expect(groups()).toEqual(['Patologia', 'Biochimica'])
  })

  it('ignora senza errori una chiave salvata che non esiste più', () => {
    localStorage.setItem('rt-pref:lessons.pins', JSON.stringify({ materia: 'MATERIA_INESISTENTE' }))
    renderDashboard()
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
  })

  it('icona intestazione verde con pin di categoria: clic sgancia la categoria senza fissare la ricerca', async () => {
    localStorage.setItem('rt-pref:lessons.pins', JSON.stringify({ materia: 'PATOLOGIA' }))
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(undefined))
    renderDashboard()

    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '2026' } })
    expect(groups()).toEqual(['Patologia', 'Biochimica'])

    const header = screen.getByRole('banner')
    const headerPin = within(header).getByRole('button', { name: 'Togli Patologia dalla cima' })
    expect(headerPin).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(headerPin)
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pins' } },
    }))
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
    expect(sessionStorage.getItem('rt.lessons.searchPin')).toBeNull()
    const normalHeaderPin = within(header).getByRole('button', { name: 'Fissa la ricerca' })
    expect(normalHeaderPin).toHaveAttribute('aria-pressed', 'false')
  })

  it('pin della ricerca: disabilitato se ricerca vuota, nasconde i pin di categoria in tutte le viste e li ripristina quando tolto', () => {
    localStorage.setItem('rt-pref:lessons.pins', JSON.stringify({ materia: 'PATOLOGIA' }))
    renderDashboard()

    // Nel raggruppamento data (nessun pin di categoria) con ricerca vuota: pulsante disabilitato
    const header = screen.getByRole('banner')
    const disabledPin = within(header).getByRole('button', { name: 'Fissa la ricerca' })
    expect(disabledPin).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(disabledPin)
    expect(sessionStorage.getItem('rt.lessons.searchPin')).toBeNull()

    // Con ricerca attiva: fissa la ricerca in sessionStorage
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '  2026  ' } })
    const searchPinBtn = within(header).getByRole('button', { name: 'Fissa la ricerca' })
    expect(searchPinBtn).not.toHaveAttribute('aria-disabled')
    fireEvent.click(searchPinBtn)

    expect(JSON.parse(sessionStorage.getItem('rt.lessons.searchPin')!)).toEqual({ q: '2026', materia: '', stato: '' })
    expect(within(header).getByRole('button', { name: 'Togli la ricerca fissata' })).toHaveAttribute('aria-pressed', 'true')

    // Passando a Per materia, i pin di categoria e le icone sui gruppi sono nascosti
    fireEvent.click(screen.getByRole('button', { name: 'Per materia' }))
    expect(screen.queryAllByTestId('group-pin')).toEqual([])
    expect(groups()).toEqual(['Biochimica', 'Patologia'])
    expect(within(header).getByRole('button', { name: 'Togli la ricerca fissata' })).toHaveAttribute('aria-pressed', 'true')

    // Togliendo il pin della ricerca, i pin di categoria riappaiono e Patologia torna in cima
    fireEvent.click(within(header).getByRole('button', { name: 'Togli la ricerca fissata' }))
    expect(sessionStorage.getItem('rt.lessons.searchPin')).toBeNull()
    expect(screen.getAllByTestId('group-pin').length).toBeGreaterThan(0)
    expect(groups()).toEqual(['Patologia', 'Biochimica'])
    expect(within(header).getByRole('button', { name: 'Togli Patologia dalla cima' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('pin della ricerca salvato in sessionStorage si riapplica aprendo la pagina senza filtri URL', () => {
    sessionStorage.setItem('rt.lessons.searchPin', JSON.stringify({ q: 'rossi', materia: 'PATOLOGIA', stato: '' }))
    renderDashboard()
    expect(screen.getByLabelText('Cerca')).toHaveValue('rossi')
    expect(screen.getByText(/Solo Patologia\./)).toBeInTheDocument()
    expect(screen.getAllByTestId('lesson-row')).toHaveLength(2)
    expect(within(screen.getByRole('banner')).getByRole('button', { name: 'Togli la ricerca fissata' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('sessionStorage che lancia eccezioni non rompe la pagina', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key?: string) => {
      if (key === 'rt.lessons.searchPin') throw new Error('SecurityError')
      return null
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
      if (key === 'rt.lessons.searchPin') throw new Error('SecurityError')
      Object.getOwnPropertyDescriptor(Storage.prototype, 'setItem')
      void value
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation((key: string) => {
      if (key === 'rt.lessons.searchPin') throw new Error('SecurityError')
    })

    renderDashboard()
    const header = screen.getByRole('banner')
    fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: '2026' } })
    fireEvent.click(within(header).getByRole('button', { name: 'Fissa la ricerca' }))
    expect(within(header).getByRole('button', { name: 'Togli la ricerca fissata' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(within(header).getByRole('button', { name: 'Togli la ricerca fissata' }))
    expect(within(header).getByRole('button', { name: 'Fissa la ricerca' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('migrazione: lessons.pinned non si applica all’avvio e viene rimossa', async () => {
    localStorage.setItem('rt-pref:lessons.pinned', JSON.stringify({
      group: 'materia',
      sort: 'titolo',
      q: 'Lipidi',
      materia: '',
      stato: '',
    }))
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(undefined))
    renderDashboard()

    expect(screen.getByLabelText('Cerca')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Per data' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/preferences/{name}', {
      params: { path: { name: 'lessons.pinned' } },
    }))
    expect(localStorage.getItem('rt-pref:lessons.pinned')).toBeNull()
  })
})
