import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { NewLessonDialog } from './NewLessonDialog'

const mutateCreate = vi.fn()

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return {
    ...actual,
    useLessons: () => ({ data: [] }),
  }
})

vi.mock('@/api/jobs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/jobs')>()
  return {
    ...actual,
    useCreateLesson: () => ({ mutate: mutateCreate, isPending: false, error: null, reset: vi.fn(), progress: null }),
    useImportLessonZips: () => ({ mutate: vi.fn(), isPending: false, error: null, reset: vi.fn(), progress: null }),
  }
})

function renderDialog(open = true, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewLessonDialog open={open} onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('NewLessonDialog', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('mostra i campi Materia, Docente, Data e Ora, e la frase di default per la pipeline', () => {
    renderDialog()
    expect(screen.getByRole('dialog', { name: 'Nuova lezione' })).toBeInTheDocument()
    expect(screen.getByLabelText('Materia')).toBeInTheDocument()
    expect(screen.getByLabelText('Docente')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Data/)).toBeInTheDocument()
    expect(screen.getByLabelText('Ora')).toBeInTheDocument()
    expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent(
      "Dopo l'importazione: trascrizione, scaletta e rielaborazione",
    )
    expect(screen.getByRole('button', { name: 'Solo trascrizione' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisione' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Arricchimento' })).toBeDisabled()
  })

  it('cambia la frase con gli interruttori Solo trascrizione e Revisione', () => {
    renderDialog()
    const soloBtn = screen.getByRole('button', { name: 'Solo trascrizione' })
    const reviewBtn = screen.getByRole('button', { name: 'Revisione' })

    // Attivando Revisione
    fireEvent.click(reviewBtn)
    expect(reviewBtn).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent(
      "Dopo l'importazione: trascrizione, scaletta, rielaborazione e revisione",
    )

    // Attivando Solo trascrizione: la revisione si disattiva
    fireEvent.click(soloBtn)
    expect(soloBtn).toHaveAttribute('aria-pressed', 'true')
    expect(reviewBtn).toBeDisabled()
    expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent(
      "Dopo l'importazione: solo trascrizione",
    )

    // Disattivando Solo trascrizione
    fireEvent.click(soloBtn)
    expect(soloBtn).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent(
      "Dopo l'importazione: trascrizione, scaletta, rielaborazione e revisione",
    )
  })

  it('invia la richiesta di creazione con i parametri corretti all\'avvio', async () => {
    renderDialog()
    const file = new File(['fake audio'], 'lezione.wav', { type: 'audio/wav' })
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), { target: { files: [file] } })
    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'FISIOLOGIA' } })
    fireEvent.change(screen.getByLabelText('Docente'), { target: { value: 'Rossi' } })
    fireEvent.change(screen.getByLabelText('Ora'), { target: { value: '10:30' } })

    // Attiva Revisione
    fireEvent.click(screen.getByRole('button', { name: 'Revisione' }))

    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(mutateCreate).toHaveBeenCalledWith(expect.objectContaining({
      materia: 'FISIOLOGIA',
      docente: 'Rossi',
      run: true,
      with_review: true,
    }), expect.anything())
  })
})
