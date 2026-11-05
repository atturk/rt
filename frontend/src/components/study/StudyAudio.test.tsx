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
  { id: '1.1', title: 'Prima unità', html: '<p>Contenuto unità 1</p>', questions: 0, pending: {} },
  { id: '1.2', title: 'Seconda unità', html: '<p>Contenuto unità 2</p>', questions: 0, pending: {} },
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
})
