import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { RelevancePage } from './relevance'

const unit = (unit_id: string, over: Record<string, unknown> = {}) => ({
  unit_id,
  title: `Unità ${unit_id}`,
  content: `Testo ${unit_id}`,
  prediction: 'didactic',
  effective: 'didactic',
  override: null,
  stale: false,
  ...over,
})

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) })

function mockApi(units: ReturnType<typeof unit>[], mode = 'active') {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/lessons/{lesson_id}/relevance') return Promise.resolve(ok({ mode, units }))
    if (path === '/api/v1/lessons/{lesson_id}/document') return Promise.resolve(ok({ sections: [{ unit_id: '1.2', start_formatted: '12:30' }] }))
    return Promise.resolve(ok({ id: 5, titolo: 'Il rene' }))
  }) as never)
  return vi.spyOn(api, 'PUT').mockResolvedValue(ok({}) as never)
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/lezioni/5/jev']}>
        <Routes>
          <Route path="/lezioni/:lessonId/jev" element={<RelevancePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const cards = () => screen.queryAllByTestId('relevance-unit')

afterEach(() => vi.restoreAllMocks())

describe('RelevancePage', () => {
  it('parte dalle possibili omissioni e passa a tutte le unità', async () => {
    mockApi([
      unit('1.1'),
      unit('1.2', { prediction: 'organizational', effective: 'organizational', confidence: 0.83, label: 'Organizzativa',
        answer: { type: 'choice', choice: 'organizational', confidence: 0.83, probabilities: { didactic: 0.1, organizational: 0.83, no_content: 0.07 } } }),
      unit('1.3', { prediction: 'no_content', effective: 'didactic', override: 'didactic' }),
    ])
    renderPage()
    expect(await screen.findByText(/Filtro attivo/)).toBeInTheDocument()
    expect(cards().map((c) => c.querySelector('h2')?.textContent)).toEqual(['1.2 · Unità 1.2 12:30', '1.3 · Unità 1.3 '])
    expect(within(cards()[0]).getByText('Confidenza: 83%')).toBeInTheDocument()
    expect(within(cards()[0]).getByText('Etichetta: Organizzativa')).toBeInTheDocument()
    expect(within(cards()[0]).getByTestId('relevance-probabilities')).toHaveTextContent('didactic 10% · organizational 83% · no_content 7%')
    fireEvent.click(screen.getByRole('button', { name: 'Tutte le unità (3)' }))
    expect(cards()).toHaveLength(3)
  })

  it('conta il campione controllato e le omissioni didattiche', async () => {
    mockApi([
      unit('1.1', { override: 'didactic' }),
      unit('1.2', { prediction: 'organizational', effective: 'didactic', override: 'didactic' }),
      unit('1.3', { prediction: 'no_content', effective: 'no_content', override: 'no_content' }),
      unit('1.4', { prediction: 'no_content', effective: 'no_content' }),
    ])
    renderPage()
    expect(await screen.findByText('Campione controllato: 3 / 4')).toBeInTheDocument()
    expect(screen.getByText('Omissioni didattiche individuate: 1')).toBeInTheDocument()
    // Riga = classe di JEV, colonne = correzione umana (didattico, organizzativo, nessun contenuto).
    const rows = within(screen.getByRole('table', { name: 'JEV → correzione umana' })).getAllByRole('row')
    const counts = (label: string) => Array.from(rows.find((r) => r.firstElementChild?.textContent === label)?.querySelectorAll('td') ?? [], (c) => c.textContent)
    expect(counts('Informazioni organizzative')).toEqual(['1', '0', '0'])
    expect(counts('Assenza di contenuto didattico')).toEqual(['0', '0', '1'])
    expect(counts('Contenuto didattico')).toEqual(['1', '0', '0'])
  })

  it('applica una correzione e ripristina la classificazione di JEV', async () => {
    const put = mockApi([unit('2.1', { prediction: 'organizational', effective: 'no_content', override: 'no_content' })])
    renderPage()
    const card = (await screen.findAllByTestId('relevance-unit'))[0]
    expect(within(card).getByText(/Corretta dall’utente/)).toBeInTheDocument()
    fireEvent.change(within(card).getByLabelText('Classificazione corretta'), { target: { value: 'didactic' } })
    fireEvent.click(within(card).getByRole('button', { name: 'Applica correzione' }))
    await vi.waitFor(() =>
      expect(put).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
        params: { path: { lesson_id: 5, unit_id: '2.1' } },
        body: { category: 'didactic' },
      }),
    )
    fireEvent.click(within(card).getByRole('button', { name: 'Ripristina JEV' }))
    await vi.waitFor(() => expect(put).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ body: { category: null } })))
  })

  it('in modalità ombra lo dice e, senza unità sospette, mostra la vista vuota', async () => {
    mockApi([unit('1.1')], 'shadow')
    renderPage()
    expect(await screen.findByText(/Modalità ombra/)).toBeInTheDocument()
    expect(screen.getByText('Nessuna unità in questa vista.')).toBeInTheDocument()
  })
})

describe('RelevancePage: assegnazione delle etichette', () => {
  it('accoda il job e a job finito rilegge le classificazioni', async () => {
    let relevanceReads = 0
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/lessons/{lesson_id}/relevance') {
        relevanceReads += 1
        return Promise.resolve(ok({ mode: 'shadow', units: [unit('1.1')] }))
      }
      if (path === '/api/v1/jobs/{job_id}') return Promise.resolve(ok({ id: 'rel-1', type: 'unit_relevance', state: 'succeeded', progress: null, error: null, result: {} }))
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      if (path === '/api/v1/lessons/{lesson_id}/document') return Promise.resolve(ok({ sections: [] }))
      return Promise.resolve(ok({ id: 5, titolo: 'Il rene' }))
    }) as never)
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({
      job_id: 'rel-1', type: 'unit_relevance', state: 'queued', lesson_id: 5, worker_available: true, retry_of: null,
    }) as never)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Riclassifica tutte' }))
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/relevance/run',
      { params: { path: { lesson_id: 5 } }, body: { force: true, mock: false } }))
    expect(await screen.findByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded')
    await vi.waitFor(() => expect(relevanceReads).toBeGreaterThan(1))
  })

  it('con JEV spento i pulsanti sono disattivati e rimandano alle impostazioni', async () => {
    mockApi([unit('1.1')], 'disabled')
    renderPage()
    expect(await screen.findByRole('button', { name: 'Assegna etichette' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Impostazioni' })).toHaveAttribute('href', '/impostazioni/modelli')
  })
})
