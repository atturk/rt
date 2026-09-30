import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { ZipImportCard } from './ZipImport'

const ok = (data: unknown, status = 200) => ({ data, error: undefined, response: new Response('{}', { status }) }) as never

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ZipImportCard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('ZipImportCard', () => {
  it('accoda il job e mostra l\'esito per archivio quando il job finisce', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({
      job_id: 'zip-job', type: 'import_lesson_zips', state: 'queued', lesson_id: null, worker_available: true, retry_of: null,
    }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      return Promise.resolve(ok({
        id: 'zip-job', type: 'import_lesson_zips', state: 'succeeded', progress: null, error: null,
        result: { imported: 1, rejected: 1, results: [
          { file: 'uno.zip', status: 'imported', lesson_id: 7 },
          { file: 'due.zip', status: 'rejected', reason: 'La lezione X esiste già.' },
        ] },
      }))
    }) as never)
    renderCard()
    const files = [new File(['PK'], 'uno.zip', { type: 'application/zip' }), new File(['PK'], 'due.zip', { type: 'application/zip' })]
    fireEvent.change(screen.getByLabelText('Archivi ZIP delle lezioni'), { target: { files } })
    fireEvent.click(screen.getByRole('button', { name: 'Importa ZIP' }))
    const list = await screen.findByRole('list', { name: 'Esito importazione ZIP' })
    expect(list).toHaveTextContent('uno.zip: importata')
    expect(list).toHaveTextContent('due.zip: rifiutata — La lezione X esiste già.')
    expect(screen.getByRole('link', { name: 'apri' })).toHaveAttribute('href', '/lezioni/7')
    expect(post.mock.calls[0][0]).toBe('/api/v1/lessons/import-zip')
    expect(screen.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded')
  })

  it('mostra subito l\'errore quando nessun archivio supera i controlli', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: undefined,
      error: { error: { code: 'invalid_archive', message: 'Nessun archivio valido da importare (a.zip: Archivio ZIP non valido.)' } },
      response: new Response('{}', { status: 422 }),
    } as never)
    vi.spyOn(api, 'GET').mockResolvedValue(ok([]))
    renderCard()
    fireEvent.change(screen.getByLabelText('Archivi ZIP delle lezioni'), { target: { files: [new File(['x'], 'a.zip')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Importa ZIP' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nessun archivio valido da importare')
    expect(screen.queryByTestId('job-progress')).toBeNull()
  })
})
