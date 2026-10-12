import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import type { SourcesView, LessonVersion } from '@/api/sources'
import { SourcesSection } from './SourcesSection'

function renderComponent(lessonId = 42) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SourcesSection lessonId={lessonId} />
    </QueryClientProvider>,
  )
}

describe('SourcesSection (Wireframe RT-fonti-materie scena 2)', () => {
  const mockView: SourcesView = {
    sources: [
      {
        id: 's_aud_1',
        tipo: 'audio',
        file: 'part1.m4a',
        impronta: 'imp1',
        aggiunta_il: '2026-10-12',
        ordine: 1,
        nome: 'Registrazione · parte 1',
        durata_s: 5520, // 1 h 32 min
        usata: true,
      },
      {
        id: 's_aud_2',
        tipo: 'audio',
        file: 'part2.m4a',
        impronta: 'imp2',
        aggiunta_il: '2026-10-12',
        ordine: 2,
        nome: 'Registrazione · parte 2',
        durata_s: 3480, // 58 min
        usata: false,
      },
      {
        id: 's_doc_1',
        tipo: 'appunti',
        file: 'appunti.txt',
        impronta: 'imp3',
        aggiunta_il: '2026-10-12',
        ordine: 3,
        nome: 'Appunti di Giulia',
        parole: 2140,
        usata: true,
      },
      {
        id: 's_mat_1',
        tipo: 'materiale',
        file: 'Slide_anemie.pdf',
        impronta: 'imp4',
        aggiunta_il: '2026-10-12',
        ordine: 4,
        nome: 'Slide_anemie.pdf',
        pagine: 34,
        usata: false,
      },
    ],
    has_unused_sources: true,
    can_undo: false,
    ultimo_aggiornamento: null,
    principale: 's_aud_1',
    ordine_usato: ['s_aud_1'],
    principale_usato: 's_aud_1',
    solo_ricostruzione: false,
  }

  const mockVersions: LessonVersion[] = [
    {
      id: 'v_2',
      il: '2026-10-12T18:40:00',
      modo: 'extend',
      fonti_aggiunte: ['parte 2', 'Slide_anemie.pdf'],
      unita_nuove: 2,
      unita_cambiate: 1,
      attuale: true,
    },
    {
      id: 'v_1',
      il: '2026-10-10T09:12:00',
      modo: 'extend',
      fonti_aggiunte: ['Appunti di Giulia'],
      unita_nuove: 1,
      unita_cambiate: 0,
      attuale: false,
    },
  ]

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/lessons/42/sources') {
        return Promise.resolve({
          data: mockView,
          error: undefined,
          response: new Response(JSON.stringify(mockView), { status: 200 }),
        } as never)
      }
      if (path === '/api/v1/lessons/42/versions') {
        return Promise.resolve({
          data: mockVersions,
          error: undefined,
          response: new Response(JSON.stringify(mockVersions), { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: {}, response: new Response('{}') } as never)
    })
  })

  it('mostra elenco fonti con misure, stellina principale e puntino non ancora usata', async () => {
    renderComponent()
    expect(await screen.findByText('Registrazione · parte 1')).toBeInTheDocument()
    expect(screen.getByText('1 h 32 min')).toBeInTheDocument()
    expect(screen.getByText('Registrazione · parte 2')).toBeInTheDocument()
    expect(screen.getByText('58 min')).toBeInTheDocument()
    expect(screen.getByText('Appunti di Giulia')).toBeInTheDocument()
    expect(screen.getByText(/2[.,\s]?140 parole/)).toBeInTheDocument()
    expect(screen.getByText('Slide_anemie.pdf')).toBeInTheDocument()
    expect(screen.getByText('34 pagine')).toBeInTheDocument()

    // Stellina sulla principale
    expect(screen.getByTestId('star-primary')).toBeInTheDocument()
    // Puntini sulle fonti non ancora usate
    const unusedDots = screen.getAllByTestId('source-unused-dot')
    expect(unusedDots).toHaveLength(2)
  })

  it('spostare una parte audio già usata chiede conferma', async () => {
    const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
      data: { ...mockView, solo_ricostruzione: true },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderComponent()
    const grip1 = await screen.findByTestId('grip-s_aud_1')

    // ArrowDown sulla parte 1 (che ha usata: true)
    fireEvent.keyDown(grip1, { key: 'ArrowDown' })

    // Popup conferma
    expect(await screen.findByText("Cambiare l'ordine delle registrazioni?")).toBeInTheDocument()
    expect(screen.getByText(/La lezione dovrà essere ricostruita/)).toBeInTheDocument()

    // Clicca Cambia
    fireEvent.click(screen.getByRole('button', { name: 'Cambia' }))

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith('/api/v1/lessons/42/sources/order', {
        body: { ids: ['s_aud_2', 's_aud_1', 's_doc_1', 's_mat_1'] },
      })
    })
  })

  it('con solo_ricostruzione mostra avviso e bottone Rimetti com\'era', async () => {
    const customView: SourcesView = {
      ...mockView,
      solo_ricostruzione: true,
      ordine_usato: ['s_aud_1', 's_aud_2'],
      principale_usato: 's_aud_1',
    }
    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/lessons/42/sources') {
        return Promise.resolve({
          data: customView,
          error: undefined,
          response: new Response(JSON.stringify(customView), { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: [], response: new Response('[]') } as never)
    })

    const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
      data: mockView,
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderComponent()
    expect(await screen.findByTestId('rebuild-required-notice')).toBeInTheDocument()
    const resetBtn = screen.getByRole('button', { name: "Rimetti com'era" })
    fireEvent.click(resetBtn)

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith('/api/v1/lessons/42/sources/order', {
        body: { ids: ['s_aud_1', 's_aud_2'] },
      })
    })
  })

  it('mostra le versioni con pulsante Ripristina che chiede conferma', async () => {
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { job_id: 'restore_job_1' },
      error: undefined,
      response: new Response('{}', { status: 202 }),
    } as never)

    renderComponent()
    const restoreBtn = await screen.findByRole('button', { name: 'Ripristina questa versione' })
    fireEvent.click(restoreBtn)

    // Dialog conferma
    expect(await screen.findByText('Ripristinare questa versione?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ripristina' }))

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/api/v1/lessons/42/versions/v_1/restore')
    })
  })
})
