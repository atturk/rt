import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
        pagine_totali: 34,
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
      fonti_aggiunte: ['s_aud_2', 's_mat_1'],
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

    // Stellina sulla principale (con l'audio, la prima parte) e nessuna stellina vuota sull'audio
    expect(screen.getByTestId('source-row-s_aud_1')).toContainElement(screen.getByTestId('star-primary'))
    expect(screen.queryByTestId('star-choose-s_aud_2')).toBeNull()
    expect(screen.getByTestId('star-choose-s_mat_1')).toBeInTheDocument()
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
    // Parte 2 spostata davanti alla 1 (entrambe usate) e appunti diventati principale
    const [aud1, aud2, doc, mat] = mockView.sources
    const customView: SourcesView = {
      ...mockView,
      sources: [aud2, doc, aud1, mat],
      principale: 's_doc_1',
      solo_ricostruzione: true,
      ordine_usato: ['s_aud_1', 's_old', 's_aud_2', 's_doc_1'],
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

    let releaseOrder!: () => void
    const putSpy = vi.spyOn(api, 'PUT').mockImplementation(((path: string) => {
      const body = path.endsWith('/order')
        ? { ...customView, sources: [aud1, doc, aud2, mat] }
        : { ...mockView, solo_ricostruzione: false }
      const response = { data: body, error: undefined, response: new Response('{}', { status: 200 }) }
      return path.endsWith('/order')
        ? new Promise((resolve) => { releaseOrder = () => resolve(response) })
        : Promise.resolve(response)
    }) as never)

    renderComponent()
    expect(await screen.findByTestId('rebuild-required-notice')).toBeInTheDocument()
    const resetBtn = screen.getByRole('button', { name: "Rimetti com'era" })
    fireEvent.click(resetBtn)

    // Tutte le fonti attuali una volta sola, con le parti usate nell'ordine di ordine_usato
    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith('/api/v1/lessons/42/sources/order', {
        body: { ids: ['s_aud_1', 's_doc_1', 's_aud_2', 's_mat_1'] },
      })
    })
    // La principale parte solo dopo la risposta dell'ordine (lucchetto senza attesa)
    expect(putSpy).toHaveBeenCalledTimes(1)
    releaseOrder()
    await waitFor(() => {
      expect(putSpy).toHaveBeenLastCalledWith('/api/v1/lessons/42/sources/primary', { body: { id: 's_aud_1' } })
    })
    expect(putSpy).toHaveBeenCalledTimes(2)
  })

  it("Rimetti com'era mostra l'errore del server", async () => {
    const [aud1, aud2, doc, mat] = mockView.sources
    const customView: SourcesView = { ...mockView, sources: [aud2, aud1, doc, mat], principale: 's_doc_1', solo_ricostruzione: true, ordine_usato: ['s_aud_1', 's_aud_2'] }
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(
      path === '/api/v1/lessons/42/sources'
        ? { data: customView, error: undefined, response: new Response('{}', { status: 200 }) }
        : { data: [], response: new Response('[]') },
    )) as never)
    const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
      data: undefined,
      error: { code: 'lesson_busy', message: 'La lezione è occupata.' },
      response: new Response('{}', { status: 409 }),
    } as never)
    renderComponent()
    fireEvent.click(await screen.findByRole('button', { name: "Rimetti com'era" }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    // L'errore dell'ordine ferma la sequenza: nessuna PUT della principale
    expect(putSpy).toHaveBeenCalledTimes(1)
  })

  it('stellina piena dove indica il server e vuota sulle altre fonti, anche con l audio', async () => {
    const docPrimary: SourcesView = { ...mockView, principale: 's_doc_1', principale_usato: 's_doc_1' }
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(
      path === '/api/v1/lessons/42/sources'
        ? { data: docPrimary, error: undefined, response: new Response('{}', { status: 200 }) }
        : { data: [], response: new Response('[]') },
    )) as never)
    const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({ data: mockView, error: undefined, response: new Response('{}', { status: 200 }) } as never)
    renderComponent()
    await screen.findByText('Appunti di Giulia')
    expect(screen.getByTestId('source-row-s_doc_1')).toContainElement(screen.getByTestId('star-primary'))
    for (const id of ['s_aud_1', 's_aud_2', 's_mat_1']) expect(screen.getByTestId(`star-choose-${id}`)).toBeInTheDocument()
    // La lezione è già costruita: cambiare principale chiede conferma
    fireEvent.click(screen.getByTestId('star-choose-s_aud_1'))
    expect(await screen.findByText("Usare un'altra fonte come principale?")).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cambia' }))
    await waitFor(() => expect(putSpy).toHaveBeenCalledWith('/api/v1/lessons/42/sources/primary', { body: { id: 's_aud_1' } }))
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
    // Poi segue il job del ripristino
    await waitFor(() => expect(api.GET).toHaveBeenCalledWith('/api/v1/jobs/{job_id}', { params: { path: { job_id: 'restore_job_1' } } }))
  })

  it('le versioni mostrano i nomi delle fonti aggiunte', async () => {
    renderComponent()
    expect(await screen.findByTestId('version-row-v_2')).toHaveTextContent('Registrazione · parte 2, Slide_anemie.pdf')
  })

  it('Aggiungi fonte apre un menu in un portale; Appunti apre il popup', async () => {
    renderComponent()
    await screen.findByText('Appunti di Giulia')
    const section = screen.getByTestId('sources-section')
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi fonte' }))
    const menu = screen.getByRole('menu', { name: 'Aggiungi fonte' })
    expect(section).not.toContainElement(menu)
    expect(Array.from(menu.querySelectorAll('[role=menuitem]')).map((item) => item.textContent)).toEqual([
      'Parte di registrazione',
      'Appunti',
      'Materiali (PDF, slide, foto)',
    ])
    fireEvent.click(screen.getByRole('menuitem', { name: 'Appunti' }))
    expect(screen.queryByRole('menu', { name: 'Aggiungi fonte' })).not.toBeInTheDocument()
    const dialog = screen.getByRole('dialog', { name: 'Aggiungi appunti' })
    expect(screen.getByPlaceholderText('Incolla o scrivi il testo degli appunti...')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByRole('dialog', { name: 'Aggiungi appunti' })).not.toBeInTheDocument()
  })

  it('una registrazione unita mostra le parti a tutta larghezza quando si apre il chip', async () => {
    const viewWithParts: SourcesView = {
      ...mockView,
      sources: [
        {
          id: 's_aud_merged',
          tipo: 'audio',
          file: 'audio completo.m4a',
          impronta: 'imp_m',
          aggiunta_il: '2026-10-12',
          ordine: 1,
          nome: 'audio completo.m4a',
          durata_s: 4800,
          usata: true,
          parti: [
            { nome: 'registrazione 1.m4a', durata: '45 min', durata_s: 2700 },
            { nome: 'registrazione 2.m4a', durata: '35 min', durata_s: 2100 },
          ],
        },
      ],
    }
    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/lessons/42/sources') {
        return Promise.resolve({
          data: viewWithParts,
          error: undefined,
          response: new Response(JSON.stringify(viewWithParts), { status: 200 }),
        } as never)
      }
      if (path === '/api/v1/lessons/42/versions') {
        return Promise.resolve({
          data: [],
          error: undefined,
          response: new Response('[]', { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: {}, response: new Response('{}') } as never)
    })
    renderComponent()
    expect(await screen.findByText('Registrazione unita')).toBeInTheDocument()
    const chip = await screen.findByRole('button', { name: '2 parti' })
    expect(chip).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('source-parts-s_aud_merged')).toBeNull()
    fireEvent.click(chip)
    const partsContainer = await screen.findByTestId('source-parts-s_aud_merged')
    expect(partsContainer).toHaveTextContent('registrazione 1.m4a')
    expect(partsContainer).toHaveTextContent('45 min')
    expect(partsContainer).toHaveTextContent('registrazione 2.m4a')
    expect(partsContainer).toHaveTextContent('35 min')
    const segments = screen.getByTestId('source-parts-bar-s_aud_merged').children
    expect(segments[0]).toHaveStyle({ flexGrow: '2700' })
    expect(segments[1]).toHaveStyle({ flexGrow: '2100' })
    fireEvent.click(chip)
    expect(screen.queryByTestId('source-parts-s_aud_merged')).toBeNull()
  })

  it('selezione multipla di audio mostra la barra con il bottone Unisci acceso di default', async () => {
    renderComponent()
    await screen.findByText('Appunti di Giulia')
    const input = document.querySelector('input[type="file"][multiple]') as HTMLInputElement
    expect(input).toBeInTheDocument()

    const file1 = new File(['a1'], 'rec1.mp3', { type: 'audio/mp3' })
    const file2 = new File(['a2'], 'rec2.mp3', { type: 'audio/mp3' })
    fireEvent.change(input, { target: { files: [file1, file2] } })

    const bar = await screen.findByTestId('pending-audios-bar')
    expect(bar).toHaveTextContent('2 parti')
    const unisciBtn = within(bar).getByTestId('merge-audio-toggle')
    expect(unisciBtn).toHaveAttribute('aria-pressed', 'true')

    // Clic per spegnerlo
    fireEvent.click(unisciBtn)
    expect(unisciBtn).toHaveAttribute('aria-pressed', 'false')
  })
})

it('chiede conferma prima di togliere una fonte usata e permette di annullare', async () => {
  vi.spyOn(api, 'GET').mockImplementation(async (path) => ({ data: String(path).endsWith('/versions') ? [] : {
    sources: [{ id: 'used', tipo: 'appunti', file: 'note.txt', impronta: 'x', aggiunta_il: '2026-10-14', ordine: 1, nome: 'Appunti', usata: true }],
    has_unused_sources: false, can_undo: false, principale: 'used', ordine_usato: ['used'], principale_usato: 'used', solo_ricostruzione: false,
  }, response: new Response() } as never))
  const remove = vi.spyOn(api, 'DELETE').mockResolvedValue({ data: undefined, response: new Response(null, { status: 204 }) } as never)
  renderComponent()
  fireEvent.click(await screen.findByRole('button', { name: 'Togli Appunti' }))
  expect(screen.getByText('Il testo della lezione contiene ancora questa parte: per toglierla serve Ricostruisci.')).toBeInTheDocument()
  expect(remove).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(remove).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Togli Appunti' }))
  fireEvent.click(screen.getByRole('button', { name: 'Togli' }))
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(1))
})
