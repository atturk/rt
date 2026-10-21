import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { GlobalFileDrop } from '@/components/shell/GlobalFileDrop'
import { EnrichmentPanel } from './EnrichmentPanel'

const mockNavigate = vi.fn()
vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) })

const sampleImages = [
  { name: 'img1.png', url: '/api/v1/lessons/5/img1.png', in_document: true, macro_ids: ['1'], descritta: true, in_assets: true },
  { name: 'img2.png', url: '/api/v1/lessons/5/img2.png', in_document: false, source: 'pdf', descritta: false, in_assets: true },
]

const sampleElements = [
  { id: 'el-1', kind: 'infographic', unit_id: '1.3', title: 'Formula del gap', status: 'proposed' },
  { id: 'el-2', kind: 'visualization', unit_id: '2.2', title: 'Diagramma di flusso', status: 'dismissed' },
  {
    id: 'el-3',
    kind: 'infographic',
    unit_id: '1.1',
    title: 'Infografica 1.1',
    status: 'ready',
    asset_image: 'assets/enrichment/gap.png',
  },
]

function mockApi() {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/lessons/{lesson_id}') return Promise.resolve(ok({ id: 5, materia: 'FISIOLOGIA' }))
    if (path === '/api/v1/archive/summary') return Promise.resolve(ok({ file: 124, da_continuare: 2 }))
    if (path === '/api/v1/lessons/{lesson_id}/sources') return Promise.resolve(ok({ sources: [] }))
    if (path === '/api/v1/lessons/{lesson_id}/images') return Promise.resolve(ok({ images: sampleImages }))
    if (path === '/api/v1/lessons/{lesson_id}/enrichment')
      return Promise.resolve(ok({ elements: sampleElements, units: [{ id: '1.3', title: 'Gap' }] }))
    if (path === '/api/v1/lessons/{lesson_id}/outline')
      return Promise.resolve(ok({ macro_sections: [{ id: '1', title: 'M1', units: [{ id: '1.3', title: 'U1.3' }] }] }))
    if (path === '/api/v1/lessons/{lesson_id}/document')
      return Promise.resolve(
        ok({
          markdown: '# Doc\n\n### 1.2 Continuità\n![img](assets/images/img1.png)\n',
          sections: [],
        }),
      )
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
  it('mostra i media della lezione con anteprima reale e gestisce il clic', async () => {
    mockApi()
    const scrollHandler = vi.fn()
    window.addEventListener('rt-editor-scroll', scrollHandler)

    renderPanel()

    expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()
    // img1.png si trova sotto ### 1.2 Continuità nel markdown, quindi l'unità rilevata è 1.2
    expect(screen.getByLabelText(/Immagine 1.2: vai nel testo/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Immagine da PDF: vai nel testo/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Infografica 1.1: vai nel testo/i)).toBeInTheDocument()

    // Anteprima reale per l'elemento completato el-3
    const previewImg = screen.getByRole('img', { name: 'Infografica 1.1' })
    expect(previewImg).toHaveAttribute('src', '/api/v1/lessons/5/assets/enrichment/gap.png')

    // Clic su un'immagine invia l'evento rt-editor-scroll
    fireEvent.click(screen.getByLabelText(/Immagine 1.2: vai nel testo/i))
    expect(scrollHandler).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { imageName: 'img1.png', unitId: '1.2' },
      }),
    )

    // Clic sull'infografica invia l'evento rt-editor-scroll
    fireEvent.click(screen.getByLabelText(/Infografica 1.1: vai nel testo/i))
    expect(scrollHandler).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { unitId: '1.1', imageName: 'gap.png' },
      }),
    )

    window.removeEventListener('rt-editor-scroll', scrollHandler)
  })

  it('le idee già generate non mostrano "Genera" nella lista idee', async () => {
    mockApi()
    renderPanel()

    expect(await screen.findByText('Formula del gap')).toBeInTheDocument()
    // Formula del gap è proposta: mostra Genera
    expect(screen.getByRole('button', { name: /Genera/i })).toBeInTheDocument()
    // L'elemento completato Infografica 1.1 non è presente nella lista idee come proposta da generare
    expect(within(screen.getByRole('list', { name: 'Elenco idee' })).queryByText('Infografica 1.1')).not.toBeInTheDocument()
  })

  it('apre la scheda di caricamento e di ricerca web', async () => {
    mockApi()
    renderPanel()

    expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

    // Clicca Aggiungi
    fireEvent.click(screen.getByRole('button', { name: /Aggiungi immagini/i }))
    expect(screen.getByText('Aggiungi PDF o foto')).toBeInTheDocument()

    // Clicca Cerca
    fireEvent.click(screen.getByRole('button', { name: /Cerca immagini sul web/i }))
    expect(screen.getByLabelText(/Immagini per unità/i)).toBeInTheDocument()
  })

  it('la ricerca web si apre in un popup: l’elenco delle unità non esce dal pannello', async () => {
    mockApi()
    renderPanel()
    expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Cerca immagini sul web/i }))
    const dialog = screen.getByRole('dialog', { name: 'Cerca immagini sul web' })
    expect(within(dialog).getByLabelText(/Immagini per unità/i)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByLabelText('Scegli unità'))
    const unit = await within(dialog).findByLabelText('1.3 U1.3')
    expect(unit.closest('label')).toHaveClass('min-w-0')
    expect(unit.closest('fieldset')).toHaveClass('min-w-0')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByRole('dialog', { name: 'Cerca immagini sul web' })).not.toBeInTheDocument()
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

it('aggiunge i file trascinati ai file scelti, ignora gli altri e impedisce il velo globale', async () => {
  const post = mockApi()
  const globalDrop = vi.fn()
  renderPanel()
  render(<GlobalFileDrop onDropFiles={globalDrop} />)
  fireEvent.click(screen.getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' }))
  const selected = new File(['pdf'], 'slide.pdf', { type: 'application/pdf' })
  const photo = new File(['photo'], 'foto.HEIC', { type: '' })
  const ignored = new File(['audio'], 'audio.wav', { type: 'audio/wav' })
  fireEvent.change(screen.getByLabelText('PDF o foto'), { target: { files: [selected] } })
  const card = screen.getByTestId('enrichment-upload')
  const dataTransfer = { types: ['Files'], files: [photo, ignored] }
  fireEvent.dragEnter(card, { dataTransfer })
  fireEvent.dragOver(card, { dataTransfer })
  expect(card).toHaveClass('border-foreground', 'bg-muted')
  expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  fireEvent.drop(card, { dataTransfer })
  expect(card).not.toHaveClass('border-foreground')
  expect(globalDrop).not.toHaveBeenCalled()
  expect(screen.getByRole('alert')).toHaveTextContent('Formato non supportato: audio.wav')
  fireEvent.click(screen.getByRole('button', { name: 'Carica (2)' }))
  await vi.waitFor(() => expect(post).toHaveBeenCalled())
  const options = post.mock.calls[0][1] as { bodySerializer: () => FormData }
  const body = options.bodySerializer()
  expect(body.getAll('files').map((file) => (file as File).name)).toEqual(['slide.pdf', 'foto.HEIC'])
})

it('AR5: illumina il pannello al trascinamento di media e apre il riquadro di caricamento al rilascio', () => {
  renderPanel()
  expect(screen.queryByTestId('enrichment-drop-veil')).not.toBeInTheDocument()
  expect(screen.queryByTestId('enrichment-upload')).not.toBeInTheDocument()

  // Drag attivo
  act(() => {
    window.dispatchEvent(
      new CustomEvent('rt-enrichment-media-drag', { detail: { active: true } }),
    )
  })
  expect(screen.getByTestId('enrichment-drop-veil')).toBeInTheDocument()
  expect(screen.getByText('Rilascia per aggiungere ai media della lezione')).toBeInTheDocument()

  // Rilascio di un PDF
  const pdf = new File(['slide content'], 'lezione-slide.pdf', { type: 'application/pdf' })
  act(() => {
    window.dispatchEvent(
      new CustomEvent('rt-enrichment-media-drop', { detail: { files: [pdf] } }),
    )
  })

  // Il velo scompare e la scheda di caricamento si apre con il file
  expect(screen.queryByTestId('enrichment-drop-veil')).not.toBeInTheDocument()
  expect(screen.getByTestId('enrichment-upload')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica (1)' })).toBeInTheDocument()
})

it('mostra i file scelti nella lista, permette di rimuoverli e Annulla li scarta', () => {
  mockApi()
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' }))

  const input = screen.getByLabelText('PDF o foto')
  const file1 = new File(['pdf1'], 'appunti.pdf', { type: 'application/pdf' })
  const file2 = new File(['img2'], 'foto.jpg', { type: 'image/jpeg' })

  // Scegliendo un file, compare nella lista "File scelti" e il pulsante dice "Carica (1)"
  fireEvent.change(input, { target: { files: [file1] } })
  const list = screen.getByRole('list', { name: 'File scelti' })
  expect(within(list).getByText('appunti.pdf')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica (1)' })).toBeEnabled()

  // Scegliendo un secondo file
  fireEvent.change(input, { target: { files: [file2] } })
  expect(within(list).getByText('foto.jpg')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica (2)' })).toBeEnabled()

  // Rimuovi toglie il file
  fireEvent.click(screen.getByRole('button', { name: 'Rimuovi appunti.pdf' }))
  expect(within(list).queryByText('appunti.pdf')).not.toBeInTheDocument()
  expect(within(list).getByText('foto.jpg')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica (1)' })).toBeEnabled()

  // Rimuovendo anche il secondo, il pulsante torna a "Carica" disabilitato
  fireEvent.click(screen.getByRole('button', { name: 'Rimuovi foto.jpg' }))
  expect(screen.queryByRole('list', { name: 'File scelti' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica' })).toBeDisabled()

  // File trascinato sulla scheda compare nella lista
  const card = screen.getByTestId('enrichment-upload')
  const dropFile = new File(['drop'], 'slide.pdf', { type: 'application/pdf' })
  fireEvent.drop(card, { dataTransfer: { types: ['Files'], files: [dropFile] } })
  const updatedList = screen.getByRole('list', { name: 'File scelti' })
  expect(within(updatedList).getByText('slide.pdf')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica (1)' })).toBeEnabled()

  // Premere Annulla e riaprire la scheda: lista vuota, Carica disabilitato
  fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(screen.queryByTestId('enrichment-upload')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' }))
  expect(screen.getByTestId('enrichment-upload')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'File scelti' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Carica' })).toBeDisabled()
})

it('di base la vista dei media è a righe, il pulsante passa a griglia e salva in localStorage', async () => {
  localStorage.removeItem('rt.media.view')
  mockApi()
  renderPanel()

  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  // Di base la vista è a righe: c'è il pulsante per passare a griglia
  const toggleBtn = screen.getByRole('button', { name: 'Vista a griglia' })
  expect(toggleBtn).toBeInTheDocument()

  // Clic passa a griglia
  fireEvent.click(toggleBtn)
  expect(localStorage.getItem('rt.media.view')).toBe('grid')
  expect(screen.getByRole('button', { name: 'Una pagina per riga' })).toBeInTheDocument()

  // Clic torna a righe
  fireEvent.click(screen.getByRole('button', { name: 'Una pagina per riga' }))
  expect(localStorage.getItem('rt.media.view')).toBe('rows')
  expect(screen.getByRole('button', { name: 'Vista a griglia' })).toBeInTheDocument()
})

it('la galleria seleziona e scrolla all’evento rt-media-select con animazione rt-media-flash', async () => {
  mockApi()
  renderPanel()
  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  const cell = await screen.findByTestId('media-cell-img1.png')
  const scrollMock = vi.fn()
  cell.scrollIntoView = scrollMock

  act(() => {
    window.dispatchEvent(
      new CustomEvent('rt-media-select', { detail: { name: 'img1.png' } }),
    )
  })

  expect(scrollMock).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
  const btn = cell.querySelector('button')
  expect(btn).toHaveAttribute('aria-pressed', 'true')
  expect(cell).toHaveClass('rt-media-flash')

  act(() => {
    fireEvent.animationEnd(cell)
  })
  expect(cell).not.toHaveClass('rt-media-flash')
})

it('rt-media-select su immagine in un gruppo chiuso apre il gruppo, scorre al centro e aggiunge rt-media-flash', async () => {
  mockApi()
  renderPanel()
  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  // Chiudi il gruppo cliccando sull'header del gruppo
  const groupHeader = screen.getByText('Altre immagini')
  fireEvent.click(groupHeader)

  // Ora la cella non è più nel DOM
  expect(screen.queryByTestId('media-cell-img1.png')).toBeNull()

  // Invia rt-media-select
  await act(async () => {
    window.dispatchEvent(
      new CustomEvent('rt-media-select', { detail: { name: 'img1.png' } }),
    )
    await new Promise((r) => setTimeout(r, 10))
  })

  // Il gruppo si è riaperto e la cella è visibile
  const cell = await screen.findByTestId('media-cell-img1.png')
  expect(cell).toBeInTheDocument()
  expect(cell).toHaveClass('rt-media-flash')
})

it('mostra il pulsante Archivio in cima con i conteggi e porta ad archivio con da', async () => {
  mockApi()
  renderPanel()

  const archiveBtn = await screen.findByTestId('open-archive-button')
  expect(archiveBtn).toBeInTheDocument()
  expect(within(archiveBtn).getByText('Archivio')).toBeInTheDocument()
  expect(await within(archiveBtn).findByText('124 file · 2 PDF da continuare')).toBeInTheDocument()

  fireEvent.click(archiveBtn)
  expect(mockNavigate).toHaveBeenCalledWith('/archivio?da=5')
})

it('filtro Da descrivere mostra il numero e il puntino arancione sulle non descritte', async () => {
  mockApi()
  renderPanel()

  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  // Bottone Da descrivere con badge conteggio (1 non descritta)
  const undescribedFilter = screen.getByTestId('filter-undescribed')
  expect(undescribedFilter).toBeInTheDocument()
  expect(within(undescribedFilter).getByText('1')).toBeInTheDocument()

  // Puntino arancione su img2.png
  const dot = screen.getByTestId('undescribed-dot')
  expect(dot).toBeInTheDocument()
  expect(dot).toHaveClass('bg-warning')

  // Clic su Da descrivere filtra la galleria
  fireEvent.click(undescribedFilter)
  expect(screen.queryByTestId('media-cell-img1.png')).not.toBeInTheDocument()
  expect(screen.getByTestId('media-cell-img2.png')).toBeInTheDocument()

  // Clic su Tutti mostra di nuovo tutte le immagini
  fireEvent.click(screen.getByTestId('filter-all'))
  expect(screen.getByTestId('media-cell-img1.png')).toBeInTheDocument()
  expect(screen.getByTestId('media-cell-img2.png')).toBeInTheDocument()
})

it('barra di selezione: Descrivi, Ritaglia e Elimina con conferma', async () => {
  const post = mockApi()
  renderPanel()

  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  // 1. Seleziona img1.png (già descritta)
  fireEvent.click(screen.getByTestId('media-cell-img1.png').querySelector('button')!)
  expect(await screen.findByTestId('media-selection-bar')).toBeInTheDocument()
  expect(screen.getByText('1 scelto')).toBeInTheDocument()

  // Descrivi disattivato perché è già descritta
  const descBtn = screen.getByTestId('describe-media-button')
  expect(descBtn).toHaveAttribute('aria-disabled', 'true')

  // Ritaglia attivo con 1 immagine selezionata
  const cropBtn = screen.getByTestId('crop-media-button')
  expect(cropBtn).not.toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(cropBtn)
  expect(mockNavigate).toHaveBeenCalledWith('/archivio?da=5&file=img1&pagina=1&ritaglia=1')

  // 2. Seleziona anche img2.png (non descritta)
  fireEvent.click(screen.getByTestId('media-cell-img2.png').querySelector('button')!)
  expect(screen.getByText('2 scelti')).toBeInTheDocument()

  // Descrivi ora attivo (c'è img2 non descritta)
  expect(descBtn).not.toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(descBtn)
  await vi.waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      '/api/v1/lessons/{lesson_id}/media/describe',
      expect.objectContaining({
        params: { path: { lesson_id: 5 } },
        body: expect.objectContaining({ names: ['img2.png'] }),
      }),
    ),
  )

  // Dopo la descrizione la selezione viene azzerata
  await vi.waitFor(() => expect(screen.queryByTestId('media-selection-bar')).not.toBeInTheDocument())

  // 3. Elimina con conferma
  // Seleziona img1 per testare elimina
  fireEvent.click(screen.getByTestId('media-cell-img1.png').querySelector('button')!)
  const deleteBtn = await screen.findByTestId('delete-media-button')
  fireEvent.click(deleteBtn)

  const confirmDialog = await screen.findByRole('dialog')
  expect(within(confirmDialog).getByText('Eliminare dalla lezione?')).toBeInTheDocument()
  fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Elimina' }))

  await vi.waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      '/api/v1/lessons/{lesson_id}/media/delete',
      expect.objectContaining({
        params: { path: { lesson_id: 5 } },
      }),
    ),
  )
})

it('nessun pulsante forbici Scissors sulle miniature della galleria', async () => {
  mockApi()
  renderPanel()
  expect(await screen.findByText(/Media della lezione · 3/)).toBeInTheDocument()

  // Nessun pulsante ritaglia o forbici nelle miniature
  const gallery = screen.getByTestId('media-gallery')
  expect(within(gallery).queryByLabelText(/Ritaglia/i)).not.toBeInTheDocument()
})


