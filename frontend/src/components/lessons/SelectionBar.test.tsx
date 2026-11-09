import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { SelectionBar } from './LessonsView'
import type { Lesson } from '@/lib/format'
import { getFileStatusSnapshot } from '@/lib/fileStatus'

const lessons: Lesson[] = [
  { id: 1, folder_name: 'a', path: '', titolo: 'Infiammazione', materia: '', data: '', docente: '', argomenti: '', ora: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, media_count: 0, phases: { build: 'VALID', rewrite: 'VALID' } },
  { id: 2, folder_name: 'b', path: '', titolo: 'Lipidi', materia: '', data: '', docente: '', argomenti: '', ora: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, media_count: 0, phases: { build: 'STALE', rewrite: 'MISSING' } },
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
  it('apre i dettagli con una riga per lezione e la tabella ordinabile', () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Dettagli della selezione' }))
    const dialog = screen.getByRole('dialog', { name: '2 lezioni selezionate' })
    expect(dialog).toHaveTextContent('Materie')
    expect(dialog).toHaveTextContent('Docenti')
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByRole('columnheader', { name: 'Costo' })).toHaveAttribute('aria-sort', 'descending')
    fireEvent.click(screen.getByRole('button', { name: 'Costo' }))
    expect(screen.getByRole('columnheader', { name: 'Costo' })).toHaveAttribute('aria-sort', 'ascending')
    fireEvent.click(screen.getByRole('button', { name: 'Chiudi' }))
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('Esporta PDF ed Esporta lezioni (.rt) accodano i job corretti e aggiornano fileStatus', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'exp-1', state: 'queued' }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string, opts?: { params?: { path?: { job_id?: string } } }) => {
      const jid = opts?.params?.path?.job_id || (path.includes('exp-') ? 'exp-1' : '')
      if (path === '/api/v1/jobs/{job_id}' || path === `/api/v1/jobs/${jid}`) {
        return Promise.resolve(ok({
          id: 'exp-1',
          state: 'succeeded',
          progress: { current: 2, total: 2, message: 'Pronto' },
          result: { included: 2, skipped: 0, files: ['Infiammazione.pdf', 'Lipidi.pdf'] },
          error: null,
        }))
      }
      return Promise.resolve(ok({}))
    }) as never)

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/files')) {
        return Promise.resolve({
          ok: true,
          json: async () => [{ name: 'Infiammazione.pdf' }, { name: 'Lipidi.pdf' }],
        })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })

    renderBar()

    // Test Esporta PDF
    const pdfBtn = screen.getByRole('button', { name: 'Esporta PDF' })
    expect(pdfBtn).toBeInTheDocument()
    fireEvent.click(pdfBtn)

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/v1/lesson-exports', {
        body: { ids: [1, 2], format: 'pdf', name: 'Lezioni selezionate', study: false },
      })
    })

    await waitFor(() => {
      const status = getFileStatusSnapshot()
      expect(status.kind).toBe('ready')
      if (status.kind === 'ready') {
        expect(status.label).toBe('2 PDF pronti')
      }
    })

    // Test Esporta lezioni (.rt)
    post.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Esporta lezioni (.rt)' }))
    const rtMenuItem = screen.getByRole('menuitem', { name: 'Esporta lezioni (.rt)' })
    fireEvent.click(rtMenuItem)

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/v1/lesson-exports', {
        body: { ids: [1, 2], format: 'zip', name: 'Lezioni selezionate', study: true },
      })
    })
  })

  it('mostra il fallimento in fileStatus senza scaricare', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'exp-2' }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/jobs/{job_id}' || path.includes('/api/v1/jobs/')) {
        return Promise.resolve(ok({
          id: 'exp-2',
          state: 'failed',
          progress: null,
          error: 'Nessuna lezione del gruppo ha un documento finale aggiornato.',
        }))
      }
      return Promise.resolve(ok({}))
    }) as never)

    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Esporta PDF' }))

    await waitFor(() => {
      const status = getFileStatusSnapshot()
      expect(status.kind).toBe('error')
      if (status.kind === 'error') {
        expect(status.message).toContain('Nessuna lezione del gruppo')
      }
    })
  })

  it('con selezione vuota i pulsanti di export sono disabilitati', () => {
    const post = vi.spyOn(api, 'POST')
    renderBar([])
    expect(screen.getByRole('button', { name: 'Dettagli della selezione' })).toHaveAttribute('aria-disabled', 'true')
    const pdfBtn = screen.getByRole('button', { name: 'Esporta PDF' })
    expect(pdfBtn).toHaveAttribute('aria-disabled', 'true')
    const zipBtn = screen.getByRole('button', { name: 'Esporta lezioni (.rt)' })
    expect(zipBtn).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(pdfBtn)
    fireEvent.click(zipBtn)
    expect(post).not.toHaveBeenCalled()
  })
})
