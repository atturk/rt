import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { onTestFinished, vi } from 'vitest'

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

const facts = vi.fn()
vi.mock('@/api/archive', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/archive')>()),
  fileFacts: (file: File) => Promise.resolve(facts(file) ?? { entry: null, pagine_totali: null, estrai: null }),
}))

vi.mock('@/api/jobs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/jobs')>()
  return {
    ...actual,
    // L'invio passa dalla coda dei caricamenti: qui risponde subito con un job accettato.
    sendLesson: (input: unknown) => Promise.resolve(mutateCreate(input, {}) ?? { job_id: 'job-1' }),
    sendLessonZips: (files: unknown, _progress: unknown, _signal: unknown, decisions?: unknown) =>
      Promise.resolve(mutateZips(files, decisions ?? {}) ?? { job_id: 'zip-1' }),
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
  facts.mockReset()
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
    expect(screen.getByRole('button', { name: 'Solo trascrizione' })).toHaveAccessibleDescription('Solo trascrizione: serve una registrazione')
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), { target: { files: [new File(['a'], 'lezione.mp3', { type: 'audio/mpeg' })] } })
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
    expect(reviewBtn).toHaveAttribute('aria-disabled', 'true')
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

  it('una lezione già presente chiede se rimpiazzarla e offre la copia prima di farlo', async () => {
    const existing = { lesson_id: 7, data: '2026-09-05', ora: '09:00', materia: 'BIOCHIMICA', titolo: 'Lipidi', argomenti: 'Lipidi', folder_name: '[2026-09-05] BIOCHIMICA - Lipidi' }
    mockImport({ imported: 0, rejected: 0, conflicts: 1, results: [{
      file: 'b.zip', archive: 'gruppo.zip', member: 'b.zip', status: 'conflict', code: 'lesson_already_present',
      reason: 'Hai già una lezione…', can_keep_both: true, existing,
      incoming: { ...existing, lesson_id: undefined, titolo: '', argomenti: 'Membrane', folder_name: '[2026-09-05] BIOCHIMICA - Membrane' },
    }] })
    const onClose = vi.fn()
    renderDialog(true, onClose)
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    const conflicts = await screen.findByTestId('import-conflicts')
    expect(onClose).not.toHaveBeenCalled()
    expect(conflicts).toHaveTextContent('BIOCHIMICA · 05/09/2026 · 09:00')
    expect(conflicts).toHaveTextContent('La tua: «Lipidi» · Nel pacchetto: «Membrane»')
    expect(within(conflicts).getByRole('button', { name: 'Continua' })).toBeDisabled()  // di base non importa
    fireEvent.click(within(conflicts).getByLabelText('Rimpiazza la mia'))
    fireEvent.click(within(conflicts).getByRole('button', { name: 'Continua' }))
    expect(within(conflicts).getByText(/Prima di rimpiazzare vuoi scaricare una copia/)).toBeInTheDocument()
    expect(within(conflicts).getByRole('button', { name: 'Scarica la copia e rimpiazza' })).toBeEnabled()
    fireEvent.click(within(conflicts).getByRole('button', { name: 'Rimpiazza senza copia' }))
    await waitFor(() => expect(mutateZips).toHaveBeenCalledTimes(2))
    const [files, decisions] = mutateZips.mock.calls[1]
    expect((files as File[]).map((f) => f.name)).toEqual(['gruppo.zip'])
    expect(decisions).toEqual([{ file: 'gruppo.zip', member: 'b.zip', action: 'replace', lesson_id: 7 }])
  })

  it('scarica la copia della lezione prima di rimpiazzarla', async () => {
    const existing = { lesson_id: 7, data: '2026-09-05', ora: '', materia: 'BIOCHIMICA', titolo: 'Lipidi', argomenti: '', folder_name: 'A' }
    mockImport({ imported: 0, rejected: 0, conflicts: 1, results: [{
      file: 'gruppo.zip', status: 'conflict', code: 'lesson_already_present', can_keep_both: false, existing, incoming: existing,
    }] })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('PK', { status: 200 }))
    const original = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL }
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:copia'), revokeObjectURL: vi.fn() })
    onTestFinished(() => { Object.assign(URL, original) })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderDialog()
    chooseZip()
    fireEvent.click(screen.getByRole('button', { name: 'Importa' }))
    const conflicts = await screen.findByTestId('import-conflicts')
    expect(within(conflicts).queryByLabelText('Tienile entrambe')).toBeNull()
    fireEvent.click(within(conflicts).getByLabelText('Rimpiazza la mia'))
    fireEvent.click(within(conflicts).getByRole('button', { name: 'Continua' }))
    fireEvent.click(within(conflicts).getByRole('button', { name: 'Scarica la copia e rimpiazza' }))
    await waitFor(() => expect(mutateZips).toHaveBeenCalledTimes(2))
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/lessons/7/export?format=zip&scope=all&study=1', { credentials: 'same-origin' })
    expect(click).toHaveBeenCalledTimes(1)
    expect(fetchSpy.mock.invocationCallOrder[0]).toBeLessThan(mutateZips.mock.invocationCallOrder[1])
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

describe('Import nuovo: fonti con il layer delle opzioni', () => {
  const choose = (...files: File[]) =>
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), { target: { files } })
  const pdf = (name: string) => new File(['pdf'], name, { type: 'application/pdf' })
  const sent = () => mutateCreate.mock.lastCall?.[0] as { principale?: string; opzioni: Record<string, unknown>; allega_materiali?: boolean }
  const start = async () => {
    fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'CHIMICA' } })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Avvia' })).toBeEnabled())
  }

  it('un file già scelto si tiene una volta sola e lo dice', () => {
    renderDialog()
    choose(new File(['audio'], 'parte1.mp3', { type: 'audio/mp3' }), pdf('slide.pdf'))
    choose(new File(['audio'], 'Parte1.MP3', { type: 'audio/mp3' }), pdf('slide.pdf'), pdf('altre.pdf'))
    expect(screen.getAllByText('parte1.mp3')).toHaveLength(1)
    expect(screen.queryByText('Parte1.MP3')).toBeNull()
    expect(screen.getAllByText('slide.pdf')).toHaveLength(1)
    expect(screen.getByText('altre.pdf')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent("Parte1.MP3, slide.pdf sono già nell'elenco")
  })

  it('un audio con estensione non supportata si rifiuta anche se il tipo è audio/*', () => {
    renderDialog()
    choose(new File(['audio'], 'vocale.opus', { type: 'audio/ogg' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Formato non supportato: vocale.opus')
  })

  it('separa audio e materiali senza graffetta né X sulle miniature', () => {
    renderDialog()
    choose(new File(['audio'], 'parte1.mp3', { type: 'audio/mp3' }), pdf('slide.pdf'))
    expect(screen.getByText('parte1.mp3')).toBeInTheDocument()
    expect(screen.getByText('slide.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Allega documenti alle unità' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Togli slide.pdf' })).toBeNull()
    expect(screen.queryByTestId('source-layer')).toBeNull()
  })

  it('un clic sulla miniatura apre e chiude il layer; con audio la guida è la registrazione', async () => {
    renderDialog()
    choose(new File(['audio'], 'parte1.mp3', { type: 'audio/mp3' }), pdf('slide.pdf'))
    const tile = screen.getByRole('button', { name: 'Opzioni slide.pdf' })
    fireEvent.click(tile)
    const layer = screen.getByTestId('source-layer')
    expect(within(layer).getByRole('button', { name: 'Guida: fonte principale' })).toHaveAccessibleDescription(/Con una registrazione la guida è l’audio/)
    expect(within(layer).getByRole('button', { name: 'Contesto: arricchisce la fonte principale' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(tile)
    expect(screen.queryByTestId('source-layer')).toBeNull()
    await start()
    expect(sent().principale).toBeUndefined()
    expect(sent().allega_materiali).toBeUndefined()
    expect(sent().opzioni).toEqual({ 'slide.pdf': { estrai: 'immagini', uso: 'contesto' } })
  })

  it('senza audio c’è sempre una guida: la prima, poi quella scelta', async () => {
    renderDialog()
    choose(pdf('appunti.pdf'), pdf('slide.pdf'))
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni appunti.pdf' }))
    let layer = screen.getByTestId('source-layer')
    expect(within(layer).getByRole('button', { name: 'Guida: fonte principale' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(layer).getByRole('button', { name: 'Contesto: arricchisce la fonte principale' })).toHaveAccessibleDescription(/Serve una guida: scegline un’altra/)
    expect(within(layer).getByRole('button', { name: 'Solo immagini' })).toHaveAttribute('aria-disabled', 'true')
    await start()
    expect(sent().principale).toBe('appunti.pdf')

    fireEvent.click(screen.getByRole('button', { name: 'Opzioni slide.pdf' }))
    layer = screen.getByTestId('source-layer')
    fireEvent.click(within(layer).getByRole('button', { name: 'Guida: fonte principale' }))
    await start()
    expect(sent().principale).toBe('slide.pdf')
    expect(sent().opzioni).toEqual({
      'appunti.pdf': { estrai: 'immagini', uso: 'contesto' },
      'slide.pdf': { estrai: 'immagini', uso: 'guida' },
    })
  })

  it('eliminando la guida passa al primo documento con testo rimasto', async () => {
    renderDialog()
    choose(pdf('uno.pdf'), pdf('due.pdf'), pdf('tre.pdf'))
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni uno.pdf' }))
    expect(within(screen.getByTestId('source-layer')).getByRole('button', { name: 'Solo immagini' })).toHaveAccessibleDescription(/La guida ha bisogno del testo/)
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni due.pdf' }))
    fireEvent.click(within(screen.getByTestId('source-layer')).getByRole('button', { name: 'Solo immagini' }))
    expect(within(screen.getByTestId('source-layer')).getByRole('button', { name: 'Integra: può aggiungere unità' })).toHaveAccessibleDescription(/Solo immagini: nessun testo da usare/)
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni tre.pdf' }))
    fireEvent.click(within(screen.getByTestId('source-layer')).getByRole('button', { name: 'Guida: fonte principale' }))
    fireEvent.click(screen.getByRole('button', { name: 'Elimina fonte' }))
    expect(screen.queryByText('tre.pdf')).toBeNull()
    await start()
    expect(sent().principale).toBe('uno.pdf')
    expect(sent().opzioni).toEqual({
      'uno.pdf': { estrai: 'immagini', uso: 'guida' },
      'due.pdf': { estrai: 'solo_immagini', uso: 'contesto' },
    })
  })

  it('i default vengono dal tipo di file e dall’orientamento del PDF; le pagine si scelgono con Da e A', async () => {
    facts.mockImplementation((file: File) => file.name === 'libro.pdf' ? { entry: null, pagine_totali: 40, estrai: 'testo' } : null)
    renderDialog()
    choose(new File(['a'], 'lezione.mp3', { type: 'audio/mpeg' }), pdf('libro.pdf'), new File(['t'], 'note.md'), new File(['i'], 'lavagna.png', { type: 'image/png' }))
    await waitFor(() => expect(facts).toHaveBeenCalledTimes(3))
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni note.md' }))
    let layer = screen.getByTestId('source-layer')
    expect(within(layer).getByRole('button', { name: 'Testo e immagini' })).toHaveAccessibleDescription(/Solo testo per Word, TXT e MD/)
    expect(within(layer).queryByRole('group', { name: 'Pagine' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni libro.pdf' }))
    layer = screen.getByTestId('source-layer')
    await waitFor(() => expect(within(layer).getByRole('button', { name: 'Testo' })).toHaveAttribute('aria-pressed', 'true'))
    fireEvent.click(within(layer).getByRole('button', { name: 'Intervallo di pagine' }))
    fireEvent.change(within(layer).getByLabelText('Da'), { target: { value: '5' } })
    fireEvent.change(within(layer).getByLabelText('A'), { target: { value: '12' } })
    await start()
    expect(sent().opzioni).toEqual({
      'libro.pdf': { estrai: 'testo', uso: 'contesto', pagine: '5-12' },
      'note.md': { estrai: 'testo', uso: 'contesto' },
      'lavagna.png': { estrai: 'immagini', uso: 'contesto' },
    })
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


it('i docenti proposti dipendono dalla materia di Nuova lezione', async () => {
  vi.spyOn(api, 'GET').mockImplementation((path) => Promise.resolve({ data: path === '/api/v1/subjects'
    ? [{ nome: 'Biologia', lezioni: 0, docenti: ['Rossi'] }, { nome: 'Chimica', lezioni: 0, docenti: ['Verdi'] }]
    : { events: [] }, response: new Response('{}') }) as never)
  renderDialog()
  const teacher = screen.getByLabelText('Docente')
  const list = document.getElementById(teacher.getAttribute('list')!)!
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'Biologia' } })
  await waitFor(() => expect(list.querySelectorAll('option')).toHaveLength(1))
  expect(list.querySelector('option')).toHaveValue('Rossi')
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'Chimica' } })
  expect(list.querySelector('option')).toHaveValue('Verdi')
})

it('accepts DOCX and TXT and sends extraction options for each file', async () => {
  const files = [new File(['word'], 'notes.docx'), new File(['text'], 'notes.txt')]
  renderDialog(true, vi.fn(), undefined, undefined, files)
  expect(await screen.findByTestId('material-thumb-0')).toBeInTheDocument()
  expect(screen.getByTestId('material-thumb-1')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'BIOCHIMICA' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Nuova lezione' }))
  await waitFor(() => expect(mutateCreate).toHaveBeenCalledWith(expect.objectContaining({
    materiali: files,
    opzioni: { 'notes.docx': { estrai: 'testo', uso: 'guida' }, 'notes.txt': { estrai: 'testo', uso: 'contesto' } },
  }), {}))
})

it('conflitto: mantiene fonti e dati, evidenzia i metadati e li lascia correggere', async () => {
  const { ApiError } = await import('@/api/client')
  mutateCreate.mockImplementation(() => { throw new ApiError(409, 'lesson_exists', 'Già presente', { lesson_id: 7, titolo: 'Lezione esistente' }) })
  const close = vi.fn()
  renderDialog(true, close, '2026-10-21', undefined, [new File(['audio'], 'lezione.mp3')])
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'PATOLOGIA' } })
  fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
  expect(await screen.findByText('Lezione esistente')).toHaveAttribute('href', '/lezioni/7')
  expect(screen.getByLabelText('Materia')).toHaveAttribute('aria-invalid', 'true')
  expect(screen.getByLabelText('Argomenti')).toHaveAttribute('aria-invalid', 'true')
  expect(close).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'ANATOMIA' } })
  expect(screen.queryByText('Lezione esistente')).toBeNull()
  expect(screen.getByLabelText('Materia')).toHaveAttribute('aria-invalid', 'false')
})

it('precompila un conflitto del worker con metadati e fonti già caricate', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const job = {
    id: 'failed-import', type: 'ingest_sources', state: 'failed',
    payload: { audio: ['/uploads/audio.wav'], materiali: ['/uploads/slide.pdf'], run: true,
      options: { date: '2026-10-21', materia: 'PATOLOGIA', argomenti: 'Cellule', docente: 'Rossi', ora: '09:00', with_review: true } },
    result: { code: 'lesson_exists', details: { lesson_id: 7, titolo: 'Lezione esistente' } },
  } as unknown as import('@/api/client').Schemas['Job']
  render(<QueryClientProvider client={client}><MemoryRouter><NewLessonDialog open onClose={vi.fn()} initialJob={job} /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByLabelText('Materia')).toHaveValue('PATOLOGIA')
  expect(screen.getByLabelText('Argomenti')).toHaveValue('Cellule')
  expect(screen.getByLabelText(/^Data/)).toHaveValue('2026-10-21')
  expect(screen.getByLabelText('Docente')).toHaveValue('Rossi')
  expect(screen.getByLabelText('Ora')).toHaveValue('09:00')
  expect(screen.getByRole('list', { name: 'Fonti già caricate' })).toHaveTextContent('audio.wavslide.pdf')
  expect(screen.getByRole('link', { name: 'Lezione esistente' })).toHaveAttribute('href', '/lezioni/7')
})
