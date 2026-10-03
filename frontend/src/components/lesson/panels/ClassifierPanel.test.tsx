import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { ClassifierPanel } from './ClassifierPanel'

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
    if (path === '/api/v1/lessons/{lesson_id}/sections') return Promise.resolve(ok({ mode: 'active', sections: [] }))
    return Promise.resolve(ok({ id: 5, titolo: 'Il rene' }))
  }) as never)
  return vi.spyOn(api, 'PUT').mockResolvedValue(ok({}) as never)
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ClassifierPanel lessonId={5} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const cards = () => screen.queryAllByTestId('relevance-unit')

afterEach(() => vi.restoreAllMocks())

describe('ClassifierPanel', () => {
  it('elenca tutte le unità con titolo ed etichetta e filtra le non didattiche', async () => {
    mockApi([
      unit('1.1'),
      unit('1.2', { prediction: 'organizational', effective: 'organizational' }),
      unit('1.3', { prediction: 'no_content', effective: 'didactic', override: 'didactic' }),
      unit('1.4', { prediction: null }),
    ])
    renderPanel()
    expect(await screen.findByText('attivo')).toBeInTheDocument()
    expect(cards()).toHaveLength(4)
    expect(within(cards()[1]).getByLabelText('Etichetta di 1.2')).toHaveValue('organizational')
    expect(within(cards()[2]).getByText(/corretta da te/)).toBeInTheDocument()
    expect(within(cards()[3]).getByText('da classificare')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Non didattiche 1/i }))
    expect(cards()).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: /Da controllare 1/i }))
    expect(cards().map((c) => within(c).getByLabelText(/Etichetta di/).getAttribute('aria-label'))).toEqual([
      'Etichetta di 1.4',
    ])
  })

  it('cambia l’etichetta dal menu e ripristina il classificatore', async () => {
    const put = mockApi([
      unit('2.1', { prediction: 'organizational', effective: 'no_content', override: 'no_content' }),
    ])
    renderPanel()
    const card = (await screen.findAllByTestId('relevance-unit'))[0]
    fireEvent.change(within(card).getByLabelText('Etichetta di 2.1'), { target: { value: 'didactic' } })
    await vi.waitFor(() =>
      expect(put).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
        params: { path: { lesson_id: 5, unit_id: '2.1' } },
        body: { category: 'didactic' },
      }),
    )

    // Clic su "ripristina" toglie la correzione
    fireEvent.click(within(card).getByRole('button', { name: /ripristina/i }))
    await vi.waitFor(() =>
      expect(put).toHaveBeenLastCalledWith('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
        params: { path: { lesson_id: 5, unit_id: '2.1' } },
        body: { category: null },
      }),
    )
  })

  it('accoda il job di classificazione e a job finito rilegge le classificazioni', async () => {
    let relevanceReads = 0
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/lessons/{lesson_id}/relevance') {
        relevanceReads += 1
        return Promise.resolve(ok({ mode: 'active', units: [unit('1.1')] }))
      }
      if (path === '/api/v1/jobs/{job_id}')
        return Promise.resolve(
          ok({ id: 'rel-1', type: 'unit_relevance', state: 'succeeded', progress: null, error: null, result: {} }),
        )
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      if (path === '/api/v1/lessons/{lesson_id}/sections') return Promise.resolve(ok({ mode: 'active', sections: [] }))
      return Promise.resolve(ok({ id: 5, titolo: 'Il rene' }))
    }) as never)
    const post = vi.spyOn(api, 'POST').mockResolvedValue(
      ok({
        job_id: 'rel-1',
        type: 'unit_relevance',
        state: 'queued',
        lesson_id: 5,
        worker_available: true,
        retry_of: null,
      }) as never,
    )
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'Riclassifica tutte' }))
    await vi.waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/relevance/run', {
        params: { path: { lesson_id: 5 } },
        body: { force: true, mock: false },
      }),
    )
    expect(await screen.findByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded')
    await vi.waitFor(() => expect(relevanceReads).toBeGreaterThan(1))
  })
})
