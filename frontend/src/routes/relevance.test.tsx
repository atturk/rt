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

function mockApi(units: ReturnType<typeof unit>[], mode = 'active', summary?: Record<string, unknown>) {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/lessons/{lesson_id}/relevance') return Promise.resolve(ok({ mode, units, summary }))
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
  it('elenca tutte le unità con titolo ed etichetta e filtra le non didattiche', async () => {
    mockApi([
      unit('1.1'),
      unit('1.2', { prediction: 'organizational', effective: 'organizational' }),
      unit('1.3', { prediction: 'no_content', effective: 'didactic', override: 'didactic' }),
      unit('1.4', { prediction: null }),
    ])
    renderPage()
    expect(await screen.findByText(/Filtro attivo/)).toBeInTheDocument()
    expect(cards()).toHaveLength(4)
    expect(within(cards()[1]).getByRole('button', { name: /1.2 · Unità 1.2\s*12:30/ })).toBeInTheDocument()
    expect(within(cards()[1]).getByLabelText('Etichetta di 1.2')).toHaveValue('organizational')
    expect(within(cards()[2]).getByText('Corretta da te')).toBeInTheDocument()
    expect(within(cards()[3]).getByText('Da classificare')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Non didattiche (1)' }))
    expect(cards()).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Da controllare (1)' }))
    expect(cards().map((c) => within(c).getByLabelText(/Etichetta di/).getAttribute('aria-label'))).toEqual(['Etichetta di 1.4'])
  })

  it('apre il testo completo e la risposta del classificatore dal titolo', async () => {
    mockApi([unit('1.2', { prediction: 'organizational', effective: 'organizational', confidence: 0.83, label: 'Organizzativa',
      answer: { type: 'choice', choice: 'organizational', confidence: 0.83, probabilities: { didactic: 0.1, organizational: 0.83, no_content: 0.07 } } })])
    renderPage()
    const card = (await screen.findAllByTestId('relevance-unit'))[0]
    expect(within(card).queryByText('Testo 1.2')).not.toBeInTheDocument()
    fireEvent.click(within(card).getByRole('button', { name: /1.2 · Unità 1.2/ }))
    expect(within(card).getByText('Testo 1.2')).toBeInTheDocument()
    expect(within(card).getByText('Confidenza: 83%')).toBeInTheDocument()
    expect(within(card).getByText('Etichetta restituita: Organizzativa')).toBeInTheDocument()
    expect(within(card).getByTestId('relevance-probabilities')).toHaveTextContent('didactic 10% · organizational 83% · no_content 7%')
  })

  it('cambia l’etichetta dal menu e ripristina il classificatore', async () => {
    const put = mockApi([unit('2.1', { prediction: 'organizational', effective: 'no_content', override: 'no_content' })])
    renderPage()
    const card = (await screen.findAllByTestId('relevance-unit'))[0]
    fireEvent.change(within(card).getByLabelText('Etichetta di 2.1'), { target: { value: 'didactic' } })
    await vi.waitFor(() =>
      expect(put).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
        params: { path: { lesson_id: 5, unit_id: '2.1' } },
        body: { category: 'didactic' },
      }),
    )
    // Tornare all'etichetta del classificatore equivale a togliere la correzione.
    fireEvent.change(within(card).getByLabelText('Etichetta di 2.1'), { target: { value: 'organizational' } })
    await vi.waitFor(() => expect(put).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ body: { category: null } })))
    fireEvent.click(within(card).getByRole('button', { name: /2.1 · Unità 2.1/ }))
    fireEvent.click(within(card).getByRole('button', { name: 'Ripristina il classificatore' }))
    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(3))
  })

  it('in modalità ombra lo dice', async () => {
    mockApi([unit('1.1')], 'shadow')
    renderPage()
    expect(await screen.findByText(/Modalità ombra/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Non didattiche (0)' }))
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

  it('con il classificatore spento i pulsanti sono disattivati e rimandano alle impostazioni', async () => {
    mockApi([unit('1.1')], 'disabled')
    renderPage()
    expect(await screen.findByRole('button', { name: 'Classifica la lezione' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Impostazioni' })).toHaveAttribute('href', '/impostazioni/modelli')
  })

  it('riassume se il classificatore è passato e quante unità hanno ogni etichetta', async () => {
    mockApi([unit('1.1'), unit('1.2', { prediction: 'organizational', effective: 'organizational' }), unit('1.3', { prediction: null, error: 'offline' })], 'active', {
      total: 3, classified: 2, errors: 1, stale: 0, missing: 0, corrected: 0, excluded: 1,
      by_outcome: { didactic: 1, organizational: 1, no_content: 0 }, by_label: { didactic: 1, organizational: 1 },
      last_run_at: '2026-09-29T10:00:00+00:00', model: 'typesafe/jev-1.13', last_run_mode: 'active',
    })
    renderPage()
    const summary = await screen.findByTestId('relevance-summary')
    expect(within(summary).getByText('Eseguito su 2 / 3 unità')).toBeInTheDocument()
    expect(within(summary).getByText(/typesafe\/jev-1.13/)).toBeInTheDocument()
    expect(within(within(summary).getByRole('list', { name: 'Unità per etichetta' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['Contenuto didattico: 2', 'Informazioni organizzative: 1', 'Assenza di contenuto didattico: 0'])
    expect(within(summary).getByText(/1 non riuscite/)).toBeInTheDocument()
    expect(within(summary).getByRole('button', { name: 'Classifica le unità nuove o cambiate' })).toBeInTheDocument()
  })

  it('dice quando il classificatore non è mai stato eseguito sulla lezione', async () => {
    mockApi([unit('1.1', { prediction: null })], 'active', {
      total: 1, classified: 0, errors: 0, stale: 0, missing: 1, corrected: 0, excluded: 0, by_outcome: {}, by_label: {},
    })
    renderPage()
    expect(await screen.findByText('Mai eseguito su questa lezione')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Classifica la lezione' })).toBeInTheDocument()
  })
})
