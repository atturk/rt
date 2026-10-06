import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { SelectionBar } from './LessonsView'
import type { Lesson } from '@/lib/format'

const lessons: Lesson[] = [
  { id: 1, folder_name: 'a', path: '', titolo: 'Infiammazione', materia: '', data: '', docente: '', argomenti: '', ora: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, phases: { build: 'VALID', rewrite: 'VALID' } },
  { id: 2, folder_name: 'b', path: '', titolo: 'Lipidi', materia: '', data: '', docente: '', argomenti: '', ora: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, phases: { build: 'STALE', rewrite: 'MISSING' } },
]
const ok = (data: unknown, status = 200) => ({ data, error: undefined, response: new Response('{}', { status }) }) as never

function renderBar(chosen = lessons) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter>
    <SelectionBar lessons={chosen} visibleLessons={lessons} onSelectAll={vi.fn()} onCancel={vi.fn()} onDeleted={vi.fn()} />
  </MemoryRouter></QueryClientProvider>)
  return client
}

afterEach(() => vi.restoreAllMocks())

describe('export nella barra di selezione', () => {
  it.each(['markdown', 'zip'] as const)('accoda %s, mostra avanzamento e scarica una volta sola a job finito', async (format) => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'exp-1', state: 'queued' }, 202))
    let state = 'running'
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      return Promise.resolve(ok({ id: 'exp-1', state, progress: { current: 1, total: 2, message: 'Esporto 2 su 2: Lipidi' }, error: null }))
    }) as never)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const client = renderBar()
    fireEvent.click(screen.getByRole('button', { name: format === 'markdown' ? 'Scarica Markdown' : 'Scarica zip' }))
    if (format === 'zip') fireEvent.click(screen.getByRole('menuitem', { name: 'Scarica zip' }))
    await screen.findByRole('progressbar')
    expect(post).toHaveBeenCalledWith('/api/v1/lesson-exports', { body: {
      ids: format === 'markdown' ? [1] : [1, 2], format, name: 'Lezioni selezionate', study: format === 'zip',
    } })
    expect(await screen.findByText(/Esporto 2 su 2: Lipidi/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scarica zip' })).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Scarica zip' }))
    expect(post).toHaveBeenCalledTimes(1)
    expect(click).not.toHaveBeenCalled()
    state = 'succeeded'
    await client.invalidateQueries({ queryKey: ['job', 'exp-1'] })
    expect(await screen.findByRole('link', { name: 'Scarica di nuovo' })).toHaveAttribute('href', '/api/v1/lesson-exports/exp-1/file')
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    await client.invalidateQueries({ queryKey: ['job', 'exp-1'] })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('mostra il fallimento senza scaricare e permette un nuovo tentativo', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'exp-2' }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(ok(path === '/api/v1/workers' ? [] : {
      id: 'exp-2', state: 'failed', progress: null, error: 'Nessuna lezione del gruppo ha un documento finale aggiornato.',
    }))) as never)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Scarica Markdown' }))
    await screen.findByText(/Nessuna lezione del gruppo/)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Scarica Markdown' })).not.toHaveAttribute('aria-disabled'))
    expect(screen.queryByRole('link', { name: 'Scarica di nuovo' })).toBeNull()
    expect(click).not.toHaveBeenCalled()
  })

  it('con selezione vuota non accoda export', () => {
    const post = vi.spyOn(api, 'POST')
    renderBar([])
    fireEvent.click(screen.getByRole('button', { name: 'Scarica Markdown' }))
    fireEvent.click(screen.getByRole('button', { name: 'Scarica zip' }))
    expect(post).not.toHaveBeenCalled()
  })
})
