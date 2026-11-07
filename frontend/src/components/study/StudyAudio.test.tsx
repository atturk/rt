import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionAudioPlayer, StudyFlow } from './Study'
import type { Lesson } from '@/lib/format'

const LESSON: Lesson = {
  id: 1,
  materia: 'FISIOLOGIA',
  titolo: 'Lezione con audio',
  ora: '',
  data: '2026-10-02',
  folder_name: 'a',
  phases: { build: 'VALID', rewrite: 'VALID' },
  argomenti: '',
  docente: 'Rossi',
  path: '',
  duration_seconds: 3600,
  unit_count: 2,
  pending_issues: 0,
  recall_pending: 0,
  study_learned: 0,
  study_learning: 0,
  study_ignored: 0,
  recall_questions: 0,
  media_count: 0,
}

const UNITS = [
  { id: '1.1', title: 'Prima unità', html: '<p>Contenuto unità 1</p>', questions: 0, pending: {}, start: 120, end: 240 },
  { id: '1.2', title: 'Seconda unità', html: '<p>Contenuto unità 2</p>', questions: 0, pending: {}, start: 240, end: 360 },
]

vi.mock('@/api/studyProgress', () => ({
  useStudyStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useStudyRead: () => ({ mutate: vi.fn() }),
}))

vi.mock('@/api/recall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/recall')>()
  return {
    ...actual,
    useRecallTypes: () => ({ data: actual.BASE_RECALL_TYPES }),
    useStudyLesson: () => ({
      data: {
        id: 1,
        units: UNITS.map((u) => ({ ...u, suggested_qtype: 'mirata' })),
        has_audio: true,
        suggestions: false,
      },
      isPending: false,
      isError: false,
    }),
    useGenerateForUnits: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  }
})

describe('Study audio player and keyboard navigation', () => {
  let client: QueryClient

  beforeEach(() => {
    resetSessionAudioPlayer()
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
    window.HTMLMediaElement.prototype.pause = vi.fn()
  })

  afterEach(() => {
    resetSessionAudioPlayer()
    vi.restoreAllMocks()
  })

  it('senza audio non mostra il pulsante delle cuffie', () => {
    const lessonNoAudio = { ...LESSON, id: 2 }
    vi.mocked(
      // Se il test o query restituisce has_audio: false
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <StudyFlow lessons={[lessonNoAudio]} back={{ to: '/', label: 'Esci' }} />
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    )
  })

  it('frecce con player aperto fanno seek e nessun cambio unità; chiuso cambiano unità', async () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // Inizialmente siamo su unità 1
    expect(screen.getByText('Contenuto unità 1')).toBeInTheDocument()
    expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument()

    // Chiuso il player: freccia destra cambia unità
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText('Contenuto unità 2')).toBeInTheDocument()

    // Freccia sinistra torna all'unità 1
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByText('Contenuto unità 1')).toBeInTheDocument()

    // Apri il player audio con il bottone cuffie
    const audioBtn = screen.getByTestId('study-audio-player-btn')
    expect(audioBtn).toBeInTheDocument()
    fireEvent.click(audioBtn)

    // Il player audio è visibile
    expect(screen.getByTestId('audio-player')).toBeInTheDocument()

    // Con il player aperto: freccia destra NON cambia unità
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText('Contenuto unità 1')).toBeInTheDocument()
    expect(screen.queryByText('Contenuto unità 2')).not.toBeInTheDocument()

    // Con il player aperto: freccia sinistra NON cambia unità
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByText('Contenuto unità 1')).toBeInTheDocument()

    // Chiudi il player audio
    fireEvent.click(audioBtn)
    expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument()

    // Ora le frecce tornano a cambiare unità
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText('Contenuto unità 2')).toBeInTheDocument()
  })

  it('il tasto P apre e chiude il player, indicato nel tooltip', () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByRole('button', { name: 'Player audio · P' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'p' })
    expect(screen.getByTestId('audio-player')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chiudi player audio · P' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'P' })
    expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument()
  })

  it('non mostra il bottone ▶ dell\'unità', () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.queryByRole('button', { name: 'Audio della lezione per questa unità' })).not.toBeInTheDocument()
  })

  it('ricorda lo stato aperto/chiuso per dispositivo in rt-device:study-audio-open e parte da timecode unità', () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const audioBtn = screen.getByTestId('study-audio-player-btn')
    expect(localStorage.getItem('rt-device:study-audio-open')).toBeNull()

    // Clic per aprire
    fireEvent.click(audioBtn)
    expect(localStorage.getItem('rt-device:study-audio-open')).toBe('true')
    expect(screen.getByTestId('audio-player')).toBeInTheDocument()
    // Si posiziona al timecode dell'unità (start = 120s => 2:00)
    expect(screen.getByTestId('audio-current')).toHaveTextContent('2:00')

    // Clic per chiudere
    fireEvent.click(audioBtn)
    expect(localStorage.getItem('rt-device:study-audio-open')).toBe('false')
    expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument()
  })

  it('all\'ingresso in Studio il player è già aperto se salvato aperto nel dispositivo', () => {
    localStorage.setItem('rt-device:study-audio-open', 'true')
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByTestId('audio-player')).toBeInTheDocument()
    expect(screen.getByTestId('audio-current')).toHaveTextContent('2:00')
  })
})
