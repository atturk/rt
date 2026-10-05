import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { NewLessonDialog } from './NewLessonDialog'

const mutateCreate = vi.fn()
const mutateZips = vi.fn()

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
    useImportLessonZips: () => ({ mutate: mutateZips, isPending: false, error: null, reset: vi.fn(), progress: null }),
  }
})

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

function renderDialog(open = true, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewLessonDialog open={open} onClose={onClose} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => {
  vi.restoreAllMocks()
  mutateCreate.mockReset()
  mutateZips.mockReset()
})

describe('NewLessonDialog', () => {

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
    expect(screen.getByRole('button', { name: 'Arricchimento' })).toBeEnabled()
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

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}') }) as never
const chooseZip = () => fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
  target: { files: [new File(['PK'], 'gruppo.zip', { type: 'application/zip' })] },
})

function mockImport(result: unknown, initialState = 'succeeded') {
  let state = initialState
  mutateZips.mockImplementation((_files, options) => options.onSuccess({ job_id: 'zip-1' }))
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(ok(path === '/api/v1/workers' ? [{ worker_id: 'w' }] : {
    id: 'zip-1', state, progress: { current: 0, total: 3, message: 'Importo 1 su 3: prima.zip' }, result, error: state === 'failed' ? 'Importazione interrotta.' : null,
  }))) as never)
  return (next: string) => { state = next }
}

const mixedResult = {
  imported: 1, rejected: 2,
  results: [
    { file: 'prima.zip', status: 'imported', lesson_id: 11 },
    { file: 'seconda.zip', status: 'rejected', code: 'duplicate_lesson', reason: 'La lezione esiste già.' },
    { file: 'terza.zip', status: 'rejected', code: 'invalid_archive', reason: 'Archivio incompleto.' },
  ],
}

describe('esito degli ZIP in Nuova lezione', () => {
  it('a job finito mostra riepilogo e Chiudi, impedisce il reimport e consente di scegliere nuovi file', async () => {
    const changeState = mockImport(mixedResult, 'running')
    const onClose = vi.fn()
    const client = renderDialog(true, onClose)
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    await screen.findByText(/Importo 1 su 3: prima.zip/)
    expect(screen.queryByTestId('chosen-files')).toBeNull()
    expect(screen.getByRole('button', { name: 'Importa' })).toBeDisabled()
    changeState('succeeded')
    await client.invalidateQueries({ queryKey: ['job', 'zip-1'] })
    const close = await within(screen.getByRole('form', { name: 'Nuova lezione' })).findByRole('button', { name: 'Chiudi' })
    expect(screen.queryByRole('button', { name: 'Importa' })).toBeNull()
    expect(screen.getByTestId('import-summary')).toHaveTextContent('1 importate, 1 già presenti, 1 rifiutate')
    expect(screen.getByRole('list', { name: "Esito dell'importazione" })).toHaveTextContent('seconda.zip: già presente')
    fireEvent.submit(screen.getByRole('form', { name: 'Nuova lezione' }))
    expect(mutateZips).toHaveBeenCalledTimes(1)
    fireEvent.click(close)
    expect(onClose).toHaveBeenCalledTimes(1)
    chooseZip()
    expect(screen.queryByTestId('import-summary')).toBeNull()
    expect(screen.getByRole('button', { name: 'Importa' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    expect(mutateZips).toHaveBeenCalledTimes(2)
  })

  it('un gruppo di più lezioni importate resta aperto con Chiudi', async () => {
    mockImport({ imported: 2, rejected: 0, results: [
      { file: 'prima.zip', status: 'imported', lesson_id: 11 },
      { file: 'seconda.zip', status: 'imported', lesson_id: 12 },
    ] })
    const onClose = vi.fn()
    renderDialog(true, onClose)
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    await within(screen.getByRole('form', { name: 'Nuova lezione' })).findByRole('button', { name: 'Chiudi' })
    expect(screen.getByTestId('import-summary')).toHaveTextContent('2 importate, 0 già presenti, 0 rifiutate')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('un solo import riuscito apre ancora la lezione', async () => {
    mockImport({ imported: 1, rejected: 0, results: [{ file: 'prima.zip', status: 'imported', lesson_id: 11 }] })
    const onClose = vi.fn()
    renderDialog(true, onClose)
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/lezioni/11'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mutateZips).toHaveBeenCalledTimes(1)
  })

  it.each(['failed', 'cancelled'])('anche un job %s richiede di scegliere di nuovo i file', async (state) => {
    mockImport(null, state)
    renderDialog()
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    await within(screen.getByRole('form', { name: 'Nuova lezione' })).findByRole('button', { name: 'Chiudi' })
    fireEvent.submit(screen.getByRole('form', { name: 'Nuova lezione' }))
    expect(screen.queryByRole('button', { name: 'Importa' })).toBeNull()
    expect(mutateZips).toHaveBeenCalledTimes(1)
  })
})
