import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { resetUploadsForTests, useUploads } from '@/lib/uploadQueue'
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
    // L'invio passa dalla coda dei caricamenti: qui risponde subito con un job accettato.
    sendLesson: (input: unknown) => Promise.resolve(mutateCreate(input, {}) ?? { job_id: 'job-1' }),
    sendLessonZips: (files: unknown) => Promise.resolve(mutateZips(files, {}) ?? { job_id: 'zip-1' }),
  }
})

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

function renderDialog(
  open = true,
  onClose = vi.fn(),
  initialDate?: string,
  initialSlotKey?: string,
  initialFiles?: File[],
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewLessonDialog
          open={open}
          onClose={onClose}
          initialDate={initialDate}
          initialSlotKey={initialSlotKey}
          initialFiles={initialFiles}
        />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => {
  vi.restoreAllMocks()
  resetUploadsForTests()
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

describe('Import nuovo (wireframe RT-import.html)', () => {
  it('separa audio e materiali e mostra miniature dei materiali', () => {
    renderDialog()
    const audio = new File(['audio'], 'parte1.mp3', { type: 'audio/mp3' })
    const pdf = new File(['pdf'], 'slide.pdf', { type: 'application/pdf' })

    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [audio, pdf] },
    })

    expect(screen.getByText('parte1.mp3')).toBeInTheDocument()
    expect(screen.getByText('slide.pdf')).toBeInTheDocument()
    expect(screen.getByTestId('materials-container')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Allega documenti alle unità' })).toBeEnabled()
  })

  it('senza audio gestisce la stellina del materiale principale e manda principale', async () => {
    renderDialog()
    const pdf1 = new File(['pdf1'], 'appunti.pdf', { type: 'application/pdf' })
    const pdf2 = new File(['pdf2'], 'slide.pdf', { type: 'application/pdf' })

    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [pdf1, pdf2] },
    })

    // Senza audio il primo documento è sempre scelto e mandato al server.
    expect(screen.getByTestId('materials-hint')).toHaveTextContent(/La scaletta segue «appunti.pdf»/)
    expect(screen.getByTestId('material-star-0')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('material-star-1')).toHaveAttribute('aria-pressed', 'false')

    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'CHIMICA' } })
    // La principale si manda anche senza clic sulla stellina.
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(mutateCreate).toHaveBeenLastCalledWith(
      expect.objectContaining({ principale: 'appunti.pdf' }),
      expect.anything(),
    )

    // Clic sulla stellina della seconda miniatura, a primo invio uscito dalla coda
    await waitFor(() => expect(screen.getByRole('button', { name: 'Avvia' })).toBeEnabled())
    fireEvent.click(screen.getByTestId('material-star-1'))
    expect(screen.getByTestId('material-star-1')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('material-star-0')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('materials-hint')).toHaveTextContent('La scaletta segue «slide.pdf»')

    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))

    expect(mutateCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        files: [],
        materiali: expect.arrayContaining([pdf1, pdf2]),
        principale: 'slide.pdf',
        allega_materiali: true,
      }),
      expect.anything(),
    )
  })

  it('togliendo la principale passa al primo materiale rimasto', () => {
    renderDialog()
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: ['uno.pdf', 'due.pdf', 'tre.pdf'].map((name) => new File(['pdf'], name, { type: 'application/pdf' })) },
    })
    fireEvent.click(screen.getByTestId('material-star-2'))
    fireEvent.click(screen.getByTestId('material-remove-2'))
    expect(screen.getByTestId('material-star-0')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('materials-hint')).toHaveTextContent('«uno.pdf»')
    fireEvent.click(screen.getByTestId('material-remove-0'))
    expect(screen.getByTestId('material-star-0')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('materials-hint')).toHaveTextContent('«due.pdf»')
  })

  it('l interruttore graffetta controlla allega_materiali', () => {
    renderDialog()
    const pdf = new File(['pdf'], 'slide.pdf', { type: 'application/pdf' })

    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [pdf] },
    })

    const clipBtn = screen.getByTestId('attach-materials-btn')
    expect(clipBtn).toHaveAttribute('aria-pressed', 'true')

    // Spegne la graffetta
    fireEvent.click(clipBtn)
    expect(clipBtn).toHaveAttribute('aria-pressed', 'false')

    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'FISICA' } })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))

    expect(mutateCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        allega_materiali: false,
      }),
      expect.anything(),
    )
  })
})

describe('Materiali accettati e ore dal calendario', () => {
  const hour = (key: string, materia: string, start: string, end: string, recorded = false) => ({
    key, materia, start_time: start, end_time: end, start_hour: 0, end_hour: 0, date: '', day_of_week: 0,
    status: 'scheduled', is_modified: false, is_recorded: recorded, docente: null,
  })
  function mockDay(hours: unknown[]) {
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(
      path === '/api/v1/calendar/day' ? ok({ date: '', day_name: '', day_number: 0, day_of_week: 0, is_today: true, hours }) : ok([]),
    )) as never)
  }
  afterEach(() => vi.useRealTimers())

  it('sceglie una seguita senza lezione e disabilita le ore annullate', async () => {
    mockDay([
      { ...hour('tpl_1', 'ANNULLATA', '08:00', '09:00'), status: 'annullata' },
      { ...hour('tpl_2', 'SEGUITA', '09:00', '10:00'), status: 'seguita' },
    ])
    renderDialog(true, vi.fn(), '2026-10-12')
    const cancelled = await screen.findByTestId('calendar-slot-0')
    expect(cancelled).toBeDisabled()
    expect(cancelled).toHaveAccessibleName('ANNULLATA - Ora annullata')
    expect(screen.getByTestId('calendar-slot-1')).toBeEnabled()
    await waitFor(() => expect(screen.getByLabelText('Materia')).toHaveValue('SEGUITA'))
  })

  it('accetta solo i materiali che il server sa leggere', () => {
    renderDialog()
    for (const accept of [screen.getByLabelText('Audio o pacchetto della lezione'), screen.getByLabelText('Altri documenti')]) {
      for (const ext of ['.pdf', '.png', '.jpg', '.jpeg', '.heic', '.pptx']) expect(accept.getAttribute('accept')).toContain(ext)
      expect(accept.getAttribute('accept')).not.toContain('image/*')
    }
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [new File(['x'], 'foto.webp', { type: 'image/webp' })] },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Formato non supportato: foto.webp')
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [new File(['x'], 'lezione.pptx', { type: '' }), new File(['x'], 'lavagna.HEIC', { type: '' })] },
    })
    expect(screen.getByText('lezione.pptx')).toBeInTheDocument()
    expect(screen.getByText('lavagna.HEIC')).toBeInTheDocument()
  })

  it("oggi sceglie l'ora appena finita e manda la chiave della voce", async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 13, 10, 40))
    mockDay([
      hour('tpl_1', 'ANATOMIA', '08:30', '09:30'),
      hour('ovr_5', 'FISIOLOGIA', '09:30', '10:30'),
      hour('tpl_3', 'CHIMICA', '11:00', '12:00'),
    ])
    renderDialog()
    await waitFor(() => expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent('collegata a FISIOLOGIA delle 09:30'))
    expect(screen.getByTestId('manual-fields')).toHaveClass('hidden')
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), {
      target: { files: [new File(['a'], 'lezione.mp3', { type: 'audio/mpeg' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(mutateCreate).toHaveBeenCalledWith(
      expect.objectContaining({ materia: 'FISIOLOGIA', ora: '09:30', calendar_entry_id: 'ovr_5', calendar_date: '2026-10-13' }),
      expect.anything(),
    )
  })

  it("oggi preferisce l'ora in corso", async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 13, 11, 15))
    mockDay([hour('tpl_1', 'ANATOMIA', '08:30', '09:30'), hour('tpl_3', 'CHIMICA', '11:00', '12:00')])
    renderDialog()
    await waitFor(() => expect(screen.getByTestId('pipeline-sentence')).toHaveTextContent('collegata a CHIMICA delle 11:00'))
  })

  it('con tutte le ore registrate mostra i campi a mano', async () => {
    mockDay([hour('tpl_1', 'ANATOMIA', '08:30', '09:30', true)])
    renderDialog()
    await screen.findByTestId('calendar-slots-section')
    expect(screen.getByTestId('manual-fields')).not.toHaveClass('hidden')
    expect(screen.getByLabelText('Materia')).toHaveValue('')
    expect(screen.getByTestId('pipeline-sentence')).not.toHaveTextContent('collegata')
  })

  it('UI2: ora scelta ha bordo di 2px primario e barretta primaria, le altre bordo normale e barretta grigia', async () => {
    mockDay([
      hour('tpl_1', 'ANATOMIA', '08:30', '09:30'),
      hour('tpl_2', 'FISIOLOGIA', '09:30', '10:30'),
    ])
    renderDialog()
    const slot0 = await screen.findByTestId('calendar-slot-0')
    const slot1 = screen.getByTestId('calendar-slot-1')

    // Cliccando su slot1, diventa selezionato
    fireEvent.click(slot1)
    expect(slot1).toHaveClass('border-2', 'border-link', 'bg-primary/20')
    expect(slot1.querySelector('span')).toHaveClass('bg-link')

    expect(slot0).toHaveClass('border', 'border-border')
    expect(slot0.querySelector('span')).toHaveClass('bg-muted-foreground/30')

    // Cliccando su slot0, lo stile si inverte
    fireEvent.click(slot0)
    expect(slot0).toHaveClass('border-2', 'border-link', 'bg-primary/20')
    expect(slot0.querySelector('span')).toHaveClass('bg-link')
    expect(slot1).toHaveClass('border', 'border-border')
    expect(slot1.querySelector('span')).toHaveClass('bg-muted-foreground/30')
  })

  it('UI1: accetta initialDate e initialSlotKey preselezionando lo slot e compilando i campi', async () => {
    mockDay([
      hour('tpl_1', 'ANATOMIA', '08:30', '09:30'),
      hour('tpl_2', 'FISIOLOGIA', '09:30', '10:30'),
    ])
    renderDialog(true, vi.fn(), '2026-10-13', 'tpl_1')
    const slot0 = await screen.findByTestId('calendar-slot-0')
    expect(slot0).toHaveClass('border-2', 'border-link')
    await waitFor(() => expect(screen.getByLabelText('Materia')).toHaveValue('ANATOMIA'))
  })

  it('AU2b: con 2 audio mostra bottone Unisci acceso di default e invia unisci: true o false', async () => {
    mockDay([])
    const f1 = new File(['a1'], 'audio1.mp3', { type: 'audio/mp3' })
    const f2 = new File(['a2'], 'audio2.mp3', { type: 'audio/mp3' })
    renderDialog(true, vi.fn(), undefined, undefined, [f1, f2])

    const unisciBtn = await screen.findByTestId('merge-audio-toggle')
    expect(unisciBtn).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/parti · .*diventano un'unica registrazione, in quest'ordine/)).toBeInTheDocument()

    // Compila materia e invia
    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'BIOCHIMICA' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Nuova lezione' }))

    expect(mutateCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        unisci: true,
      }),
      expect.anything(),
    )

    // Il primo invio esce dalla coda dei caricamenti, poi si cambia e si rimanda
    await waitFor(() => expect(unisciBtn).toBeEnabled())
    fireEvent.click(unisciBtn)
    expect(unisciBtn).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText(/restano 2 fonti separate/)).toBeInTheDocument()

    fireEvent.submit(screen.getByRole('form', { name: 'Nuova lezione' }))
    expect(mutateCreate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        unisci: false,
      }),
      expect.anything(),
    )
  })
})

describe('caricamento in background', () => {
  it('chiusa la finestra il caricamento continua e a fine invio non si cambia pagina', async () => {
    let accept!: (v: { job_id: string }) => void
    mutateCreate.mockImplementation(() => new Promise((resolve) => { accept = resolve }))
    const pdf = new File(['pdf'], 'slide.pdf', { type: 'application/pdf' })
    const client = new QueryClient()
    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewLessonDialog open onClose={vi.fn()} initialFiles={[pdf]} />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'FISICA' } })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(await screen.findByTestId('upload-status')).toHaveTextContent('Puoi chiudere la finestra')
    view.rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const { result } = renderHook(() => useUploads())
    expect(result.current.map((u) => u.state)).toEqual(['uploading'])
    accept({ job_id: 'job-9' })
    await waitFor(() => expect(result.current).toEqual([]))
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/)
  })
})

