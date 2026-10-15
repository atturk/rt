import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LessonUpdateBar } from './LessonUpdateBar'
import type { SourcesView } from '@/api/sources'

let mockSourcesData: SourcesView | null = null
const mockUpdateMutate = vi.fn()
const mockUndoMutate = vi.fn()
const mockReorderMutate = vi.fn()
const mockPrimaryMutate = vi.fn()
const mockStartJob = vi.fn()
let mockJob = { running: false, percent: null as number | null, message: null as string | null, error: null as string | null }
let mockUpdateError: Error | null = null

vi.mock('@/api/sources', () => ({
  useSources: () => ({ data: mockSourcesData }),
  useUpdateLesson: () => ({ mutate: mockUpdateMutate, isPending: false, error: mockUpdateError }),
  useUndoUpdate: () => ({ mutate: mockUndoMutate, isPending: false, error: null }),
  useResetSelection: () => ({ mutate: mockReorderMutate, isPending: false, error: null }),
  useSetPrimarySource: () => ({ mutate: mockPrimaryMutate, isPending: false, error: null }),
  useSourcesJob: () => ({ ...mockJob, start: mockStartJob }),
}))

function renderBar(lessonId = 1) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LessonUpdateBar lessonId={lessonId} />
    </QueryClientProvider>,
  )
}

describe('LessonUpdateBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSourcesData = null
    mockJob = { running: false, percent: null, message: null, error: null }
    mockUpdateError = null
  })

  it('non mostra nulla se non ci sono fonti non usate né ricostruzione necessaria', () => {
    mockSourcesData = {
      sources: [
        {
          id: 's1',
          tipo: 'audio',
          file: 'p1.mp3',
          impronta: 'fp1',
          aggiunta_il: '2026-10-10',
          ordine: 1,
          nome: 'Parte 1',
          usata: true,
        },
      ],
      has_unused_sources: false,
      can_undo: false,
      ultimo_aggiornamento: null,
      principale: 's1',
      ordine_usato: ['s1'],
      principale_usato: 's1',
      solo_ricostruzione: false,
    }

    const { container } = renderBar()
    expect(container.firstChild).toBeNull()
  })

  it('mostra riga fonti nuove con pulsante Aggiorna, Estendi e Ricostruisci', () => {
    mockSourcesData = {
      sources: [
        {
          id: 's1',
          tipo: 'audio',
          file: 'p1.mp3',
          impronta: 'fp1',
          aggiunta_il: '2026-10-10',
          ordine: 1,
          nome: 'Parte 1',
          usata: true,
        },
        {
          id: 's2',
          tipo: 'audio',
          file: 'p2.mp3',
          impronta: 'fp2',
          aggiunta_il: '2026-10-10',
          ordine: 2,
          nome: 'Parte 2',
          usata: false,
        },
      ],
      has_unused_sources: true,
      can_undo: false,
      ultimo_aggiornamento: null,
      principale: 's1',
      ordine_usato: ['s1'],
      principale_usato: 's1',
      solo_ricostruzione: false,
    }

    renderBar()

    expect(screen.getByTestId('lesson-update-bar')).toHaveAttribute('data-state', 'new')
    expect(screen.getByText(/Fonti nuove non ancora usate: Parte 2/i)).toBeInTheDocument()

    // Clic (o tocco) su Aggiorna: apre Estendi e Ricostruisci, non avvia niente
    expect(screen.getByTestId('bar-split')).toHaveClass('hidden')
    fireEvent.click(screen.getByTestId('bar-update-main-btn'))
    expect(mockUpdateMutate).not.toHaveBeenCalled()
    expect(screen.getByTestId('bar-split')).toHaveClass('flex')
    expect(screen.getByTestId('bar-update-main-btn')).toHaveAttribute('aria-expanded', 'true')

    // Clic su Estendi esplicito: a job accettato si segue il job
    fireEvent.click(screen.getByTestId('bar-extend-btn'))
    expect(mockUpdateMutate).toHaveBeenCalledWith('extend', expect.anything())
    mockUpdateMutate.mock.calls[0][1].onSuccess({ job_id: 'job-7' })
    expect(mockStartJob).toHaveBeenCalledWith('job-7')

    // Clic su Ricostruisci: apre modale di conferma
    fireEvent.click(screen.getByTestId('bar-rebuild-btn'))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ricostruisci' }))
    expect(mockUpdateMutate).toHaveBeenCalledWith('rebuild', expect.anything())
  })

  it('mostra opzione Rendi principale l audio se la lezione ha come principale un documento', () => {
    mockSourcesData = {
      sources: [
        {
          id: 'doc1',
          tipo: 'materiale',
          file: 'slide.pdf',
          impronta: 'fp1',
          aggiunta_il: '2026-10-10',
          ordine: 1,
          nome: 'Slide.pdf',
          usata: true,
        },
        {
          id: 's1',
          tipo: 'audio',
          file: 'p1.mp3',
          impronta: 'fp2',
          aggiunta_il: '2026-10-11',
          ordine: 2,
          nome: 'Registrazione',
          usata: false,
        },
      ],
      has_unused_sources: true,
      can_undo: false,
      ultimo_aggiornamento: null,
      principale: 'doc1',
      ordine_usato: ['doc1'],
      principale_usato: 'doc1',
      solo_ricostruzione: false,
    }

    renderBar()

    const primBtn = screen.getByTestId('bar-set-audio-primary-btn')
    expect(primBtn).toBeInTheDocument()

    fireEvent.click(primBtn)
    expect(screen.getByText('Usare la registrazione come fonte principale?')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Usa come principale' }))
    expect(mockPrimaryMutate).toHaveBeenCalledWith('s1')
  })

  it('gestisce solo_ricostruzione con Rimetti com era e Ricostruisci', () => {
    mockSourcesData = {
      sources: [
        {
          id: 's2',
          tipo: 'audio',
          file: 'p2.mp3',
          impronta: 'fp2',
          aggiunta_il: '2026-10-10',
          ordine: 1,
          nome: 'Parte 2',
          usata: true,
        },
        {
          id: 's1',
          tipo: 'audio',
          file: 'p1.mp3',
          impronta: 'fp1',
          aggiunta_il: '2026-10-10',
          ordine: 2,
          nome: 'Parte 1',
          usata: true,
        },
      ],
      has_unused_sources: false,
      can_undo: false,
      ultimo_aggiornamento: null,
      principale: 's2',
      ordine_usato: ['s1', 's2'],
      principale_usato: 's1',
      solo_ricostruzione: true,
    }

    renderBar()

    expect(screen.getByTestId('lesson-update-bar')).toHaveAttribute('data-state', 'rebuild')
    expect(screen.getByText(/Ordine delle registrazioni cambiato: la lezione va ricostruita/i)).toBeInTheDocument()

    // Rimetti com'era: una sola mutazione che rimanda ordine e principale in sequenza
    fireEvent.click(screen.getByTestId('bar-reset-btn'))
    expect(mockReorderMutate).toHaveBeenCalledWith(mockSourcesData)
    expect(mockPrimaryMutate).not.toHaveBeenCalled()

    // Ricostruisci con conferma
    fireEvent.click(screen.getByTestId('bar-solo-rebuild-btn'))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ricostruisci' }))
    expect(mockUpdateMutate).toHaveBeenCalledWith('rebuild', expect.anything())
  })

  it('mostra stato Lezione aggiornata con Annulla e pulsante Chiudi', () => {
    mockSourcesData = {
      sources: [],
      has_unused_sources: false,
      can_undo: true,
      ultimo_aggiornamento: {
        modo: 'extend',
        unita_nuove: 2,
        unita_cambiate: 1,
        il: '2026-10-12T18:00:00Z',
      },
      principale: 's1',
      ordine_usato: ['s1'],
      principale_usato: 's1',
      solo_ricostruzione: false,
    }

    renderBar()

    expect(screen.getByTestId('lesson-update-bar')).toHaveAttribute('data-state', 'done')
    expect(screen.getByText(/Lezione aggiornata · 2 unità nuove, 1 cambiata/i)).toBeInTheDocument()

    // Clic su Annulla aggiornamento
    fireEvent.click(screen.getByTestId('bar-undo-btn'))
    expect(mockUndoMutate).toHaveBeenCalled()

    // Clic su Chiudi (X): nasconde la barra nel client
    fireEvent.click(screen.getByTestId('bar-close-btn'))
    expect(screen.queryByTestId('lesson-update-bar')).not.toBeInTheDocument()
  })

  it("durante il job mostra l'avanzamento e niente Aggiorna", () => {
    mockSourcesData = {
      sources: [], has_unused_sources: true, can_undo: false, ultimo_aggiornamento: null,
      principale: '', ordine_usato: [], principale_usato: null, solo_ricostruzione: false,
    }
    mockJob = { running: true, percent: 40, message: 'Scaletta', error: null }
    renderBar()
    expect(screen.getByTestId('lesson-update-bar')).toHaveAttribute('data-state', 'run')
    expect(screen.getByText(/Aggiornamento in corso · Estendi · Scaletta/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(screen.queryByTestId('bar-update-main-btn')).toBeNull()
  })

  it("mostra l'errore dell'aggiornamento (409)", () => {
    mockSourcesData = {
      sources: [], has_unused_sources: true, can_undo: false, ultimo_aggiornamento: null,
      principale: '', ordine_usato: [], principale_usato: null, solo_ricostruzione: false,
    }
    mockUpdateError = new Error('La lezione è occupata.')
    renderBar()
    expect(screen.getByRole('alert')).toHaveTextContent('La lezione è occupata.')
  })

  it('la riga torna con un nuovo aggiornamento dopo la ×', () => {
    const view = (il: string): SourcesView => ({
      sources: [], has_unused_sources: false, can_undo: true,
      ultimo_aggiornamento: { modo: 'extend', unita_nuove: 1, unita_cambiate: 0, il },
      principale: '', ordine_usato: [], principale_usato: null, solo_ricostruzione: false,
    })
    mockSourcesData = view('2026-10-12T18:00:00Z')
    const queryClient = new QueryClient()
    const ui = () => <QueryClientProvider client={queryClient}><LessonUpdateBar lessonId={1} /></QueryClientProvider>
    const { rerender } = render(ui())
    fireEvent.click(screen.getByTestId('bar-close-btn'))
    expect(screen.queryByTestId('lesson-update-bar')).toBeNull()
    rerender(ui())
    expect(screen.queryByTestId('lesson-update-bar')).toBeNull()
    mockSourcesData = view('2026-10-13T09:00:00Z')
    rerender(ui())
    expect(screen.getByTestId('lesson-update-bar')).toHaveAttribute('data-state', 'done')
  })
})

it('le fonti usate tolte offrono solo Ricostruisci e Rimetti come era', () => {
  mockSourcesData = { sources: [], has_unused_sources: false, can_undo: false, principale: '', ordine_usato: ['s1'], principale_usato: 's1', solo_ricostruzione: true, fonti_tolte_usate: ['s1'] }
  renderBar()
  expect(screen.getByText('Hai tolto una fonte già usata')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ricostruisci' })).toBeInTheDocument()
  expect(screen.queryByTestId('bar-extend-btn')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: "Rimetti com'era" }))
  expect(mockReorderMutate).toHaveBeenCalledWith(mockSourcesData)
})
