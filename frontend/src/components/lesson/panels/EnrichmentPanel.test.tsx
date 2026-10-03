import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { EnrichmentPanel } from './EnrichmentPanel'

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) })

const sampleImages = [
  { name: 'img1.png', url: '/api/v1/lessons/5/img1.png', in_document: true, macro_ids: ['1.2'] },
  { name: 'img2.png', url: '/api/v1/lessons/5/img2.png', in_document: false, source: 'pdf' },
]

const sampleElements = [
  { id: 'el-1', kind: 'infographic', unit_id: '1.3', title: 'Formula del gap', status: 'proposed' },
  { id: 'el-2', kind: 'visualization', unit_id: '2.2', title: 'Diagramma di flusso', status: 'dismissed' },
]

function mockApi() {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/lessons/{lesson_id}/images') return Promise.resolve(ok({ images: sampleImages }))
    if (path === '/api/v1/lessons/{lesson_id}/enrichment')
      return Promise.resolve(ok({ elements: sampleElements, units: [{ id: '1.3', title: 'Gap' }] }))
    if (path === '/api/v1/lessons/{lesson_id}/outline')
      return Promise.resolve(ok({ macro_sections: [{ id: '1', title: 'M1', units: [{ id: '1.3', title: 'U1.3' }] }] }))
    return Promise.resolve(ok({}))
  }) as never)
  return vi.spyOn(api, 'POST').mockResolvedValue(ok({ job_id: 'j1' }) as never)
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EnrichmentPanel lessonId={5} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('EnrichmentPanel', () => {
  it('mostra i media della lezione e clicca su un elemento', async () => {
    mockApi()
    renderPanel()

    expect(await screen.findByText(/Media della lezione · 2/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Immagine 1.2: vai nel testo/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Immagine da PDF: vai nel testo/i)).toBeInTheDocument()
  })

  it('apre la scheda di caricamento e di ricerca web', async () => {
    mockApi()
    renderPanel()

    expect(await screen.findByText(/Media della lezione · 2/)).toBeInTheDocument()

    // Clicca Aggiungi
    fireEvent.click(screen.getByRole('button', { name: /Aggiungi immagini/i }))
    expect(screen.getByText('Aggiungi PDF o foto')).toBeInTheDocument()

    // Clicca Cerca
    fireEvent.click(screen.getByRole('button', { name: /Cerca immagini sul web/i }))
    expect(screen.getByLabelText(/Immagini per unità/i)).toBeInTheDocument()
  })

  it('mostra le idee e permette di generare o ignorare', async () => {
    const post = mockApi()
    renderPanel()

    expect(await screen.findByText('Formula del gap')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Genera/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ignora' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Genera/i }))
    await vi.waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/v1/lessons/{lesson_id}/enrichment/generate',
        expect.objectContaining({
          params: { path: { lesson_id: 5 } },
          body: expect.objectContaining({ element_id: 'el-1' }),
        }),
      ),
    )

    // Clicca ignora
    fireEvent.click(screen.getByRole('button', { name: 'Ignora' }))
    await vi.waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/v1/lessons/{lesson_id}/enrichment/{element_id}/action',
        expect.objectContaining({
          params: { path: { lesson_id: 5, element_id: 'el-1' } },
          body: { action: 'dismiss' },
        }),
      ),
    )

    // Mostra ignorate
    expect(screen.getByRole('button', { name: /Mostra le 1 idee ignorate/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Mostra le 1 idee ignorate/i }))
    expect(screen.getByText('Diagramma di flusso')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ripristina' })).toBeInTheDocument()
  })
})
