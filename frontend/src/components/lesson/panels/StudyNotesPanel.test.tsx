import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StudyNotesPanel } from './StudyNotesPanel'
import type { StudyNote } from '@/api/studyNotes'
import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'

const mockNotes: StudyNote[] = [
  {
    id: 1,
    lesson_id: 10,
    unit_id: '1.1',
    unit_fingerprint: 'fp1',
    kind: 'verifica',
    anchor: { quote: '93 mmHg', prefix: '', suffix: '', start: 0, end: 7 },
    anchor_state: 'trovata',
    current_quote: '93 mmHg',
    request: 'Controlla valore',
    response: {
      esito: 'errato',
      spiegazione: 'Il valore corretto è tra 70 e 105 mmHg.',
      correzione: 'tra 70 e 105 mmHg',
    },
    model: 'gpt-4o',
    cost: 0.003,
    created_at: '2026-10-11T10:00:00Z',
    applied_decision_id: null,
    precedente: true,
  },
  {
    id: 2,
    lesson_id: 10,
    unit_id: '1.1',
    unit_fingerprint: 'fp1',
    kind: 'chiedi',
    anchor: { quote: 'compensazione renale', prefix: '', suffix: '', start: 10, end: 30 },
    anchor_state: 'cambiata',
    current_quote: 'compensazione metabolica',
    request: 'Spiega in breve',
    response: {
      spiegazione: 'Il rene impiega 24-48 ore per modulare i bicarbonati.',
    },
    model: 'gpt-4o',
    cost: 0.002,
    created_at: '2026-10-11T10:05:00Z',
    applied_decision_id: null,
  },
  {
    id: 3,
    lesson_id: 10,
    unit_id: '1.2',
    unit_fingerprint: 'fp2',
    kind: 'verifica',
    anchor: { quote: 'acidosi metabolica', prefix: '', suffix: '', start: 0, end: 18 },
    anchor_state: 'trovata',
    current_quote: 'acidosi metabolica',
    request: '',
    response: {
      esito: 'corretto',
      spiegazione: 'La definizione è accurata.',
    },
    model: 'gpt-4o',
    cost: 0.001,
    created_at: '2026-10-11T10:10:00Z',
    applied_decision_id: null,
  },
]

const mutateApply = vi.fn()
const mutateDelete = vi.fn()

vi.mock('@/api/studyNotes', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/studyNotes')>()
  return {
    ...actual,
    useStudyNotes: () => ({
      data: mockNotes,
      isLoading: false,
    }),
    useApplyStudyNote: () => ({
      mutate: mutateApply,
      isPending: false,
    }),
    useDeleteStudyNote: () => ({
      mutate: mutateDelete,
      isPending: false,
    }),
  }
})

function renderPanel(props: Partial<Parameters<typeof StudyNotesPanel>[0]> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <StudyNotesPanel lessonId={10} {...props} />
    </QueryClientProvider>,
  )
}

describe('StudyNotesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders list grouped by unit and shows counts', () => {
    renderPanel()

    expect(screen.getByTestId('study-notes-panel')).toBeInTheDocument()
    expect(screen.getByTestId('notes-unit-1.1')).toBeInTheDocument()
    expect(screen.getByTestId('notes-unit-1.2')).toBeInTheDocument()

    expect(screen.getByText('93 mmHg')).toBeInTheDocument()
    expect(screen.getByText('compensazione metabolica')).toBeInTheDocument()
    expect(screen.getByText('acidosi metabolica')).toBeInTheDocument()
  })

  it('filters by Tutte / Verifiche / Chiedi', () => {
    renderPanel()

    // Verifiche filter
    fireEvent.click(screen.getByTestId('filter-verifica'))
    expect(screen.getByText('93 mmHg')).toBeInTheDocument()
    expect(screen.getByText('acidosi metabolica')).toBeInTheDocument()
    expect(screen.queryByText('compensazione metabolica')).not.toBeInTheDocument()

    // Chiedi filter
    fireEvent.click(screen.getByTestId('filter-chiedi'))
    expect(screen.queryByText('93 mmHg')).not.toBeInTheDocument()
    expect(screen.getByText('compensazione metabolica')).toBeInTheDocument()

    // Tutte filter
    fireEvent.click(screen.getByTestId('filter-tutte'))
    expect(screen.getByText('93 mmHg')).toBeInTheDocument()
    expect(screen.getByText('compensazione metabolica')).toBeInTheDocument()
  })

  it('navigates to detail view when clicking an item and can go back', () => {
    const onSelectNote = vi.fn()
    renderPanel({ onSelectNote })

    fireEvent.click(screen.getByTestId('note-item-1'))
    expect(onSelectNote).toHaveBeenCalledWith(1)
    expect(screen.getByTestId('study-notes-detail')).toBeInTheDocument()
    expect(screen.getByTestId('detail-quote')).toHaveTextContent('93 mmHg')
    expect(screen.getByTestId('detail-verdict')).toHaveTextContent('Errato')
    expect(screen.getByTestId('detail-answer')).toHaveTextContent('Il valore corretto è tra 70 e 105 mmHg.')
    expect(screen.getByTestId('detail-fix')).toHaveTextContent('tra 70 e 105 mmHg')

    // Go back
    fireEvent.click(screen.getByTestId('study-notes-back'))
    expect(onSelectNote).toHaveBeenCalledWith(null)
  })

  it('applies correction in detail view', () => {
    renderPanel({ selectedNoteId: 1 })

    expect(screen.getByTestId('study-notes-detail')).toBeInTheDocument()
    const applyBtn = screen.getByTestId('detail-apply')
    expect(applyBtn).toBeEnabled()
    fireEvent.click(applyBtn)

    expect(mutateApply).toHaveBeenCalledWith(1)
  })

  it('dispatches EDITOR_SCROLL_EVENT on "Vai all\'unità"', () => {
    const handler = vi.fn()
    window.addEventListener(EDITOR_SCROLL_EVENT, handler)

    renderPanel({ selectedNoteId: 1 })
    fireEvent.click(screen.getByTestId('detail-goto'))

    expect(handler).toHaveBeenCalled()
    window.removeEventListener(EDITOR_SCROLL_EVENT, handler)
  })

  it('copies answer to clipboard on "Copia la risposta"', () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    renderPanel({ selectedNoteId: 1 })
    fireEvent.click(screen.getByTestId('detail-copy'))

    expect(writeText).toHaveBeenCalledWith('Il valore corretto è tra 70 e 105 mmHg.')
  })

  it('shows warning when text has changed', () => {
    renderPanel({ selectedNoteId: 2 })

    expect(screen.getByText(/Il testo è cambiato dopo la domanda/i)).toBeInTheDocument()
  })

  it('mostra icona precedente con tooltip nelle note precedenti', () => {
    const { unmount } = renderPanel()
    expect(screen.getByTestId('note-precedente-icon')).toBeInTheDocument()
    unmount()

    renderPanel({ selectedNoteId: 1 })
    expect(screen.getByTestId('note-precedente-icon')).toBeInTheDocument()
  })
})
