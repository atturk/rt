import { KnownBadge } from '@/components/sources/ArchiveFileBadge'
import { ExtractOptions, PagesOptions, SourceBadges, SourceFileIcon, UseOptions } from '@/components/sources/SourceControls'
import { fileFacts, textOnly, type SourceOptions } from '@/api/archive'
import { defaultOptions, hasPages, sourceReasons, useSourceDefaults } from '@/lib/sourceDefaults'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  Check,
  Ban,
  ChevronLeft,
  ChevronRight,
  FileAudio,
  FileText,
  Image,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { api, unwrap, type Schemas, ApiError, errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { useSubjects, useTeacherSuggestions } from '@/api/subjects'
import { calendarApi, calendarKeys, type CalendarEventView } from '@/api/calendar'
import {
  invalidateAfterJob,
  sendLesson,
  sendLessonZips,
  type NewLesson,
  type ZipImportDecision,
  type ZipImportResult,
} from '@/api/jobs'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { JobProgress } from '@/components/JobProgress'
import { AudioOrder } from '@/components/lessons/AudioOrder'
import { ImportConflicts } from '@/components/lessons/ImportConflicts'
import { MergeAudioToggle } from '@/components/lessons/MergeAudioToggle'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
import { AUDIO_EXTENSIONS, formatBytes } from '@/lib/jobs'
import { cancelUpload, enqueueUpload, isUploadActive, useUpload, type UploadSend } from '@/lib/uploadQueue'
import { cn } from '@/lib/utils'

const DROP_LABEL = "Trascina l'audio o il pacchetto della lezione, o fai clic"
const DROP_TEXT = "Trascina qui l'audio della lezione, slide, PDF o foto, oppure un pacchetto .zip. Clic per scegliere."

// Stesso insieme di rt/core/materials.py (MATERIAL_EXTENSIONS): il server rifiuta il resto.
const MATERIAL_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.heic', '.pptx', '.docx', '.txt', '.md']

function isAudioFile(file: File): boolean {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  // Solo l'estensione: un .opus o un .webm con tipo audio/* il server lo rifiuterebbe a upload finito.
  return AUDIO_EXTENSIONS.includes(ext)
}

function isMaterialFile(file: File): boolean {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  return MATERIAL_EXTENSIONS.includes(ext)
}

const minutesOf = (time: string) => {
  const [h, m] = time.split(':').map(Number)
  return h * 60 + (m || 0)
}

/**
 * Ora proposta all'apertura: oggi quella in corso o, se nessuna, l'ultima appena finita;
 * negli altri giorni (o prima delle lezioni) la prima non ancora registrata.
 */
function pickSlot(hours: CalendarEventView[], date: string, now = new Date()) {
  const free = hours.filter((h) => !h.is_recorded && h.status !== 'annullata')
  if (free.length === 0) return null
  if (date === today()) {
    const current = now.getHours() * 60 + now.getMinutes()
    const running = free.find(
      (h) => minutesOf(h.start_time) <= current && current < minutesOf(h.end_time),
    )
    if (running) return running
    const ended = free.filter((h) => minutesOf(h.end_time) <= current)
    if (ended.length > 0) {
      return ended.reduce((a, b) => (minutesOf(b.end_time) > minutesOf(a.end_time) ? b : a))
    }
  }
  return free[0]
}

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatDayLabel(dateStr: string): string {
  const parts = dateStr.split('-').map(Number)
  if (parts.length !== 3 || parts.some(isNaN)) return dateStr
  const d = new Date(parts[0], parts[1] - 1, parts[2])
  const isToday = dateStr === today()
  const days = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato']
  const months = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']
  const dayName = days[d.getDay()]
  const dayNum = d.getDate()
  const monthName = months[d.getMonth()]
  return `${isToday ? 'Oggi, ' : ''}${dayName} ${dayNum} ${monthName}`
}

const isZip = (file: File) => file.name.toLowerCase().endsWith('.zip')

/** Il server rifiuta due file con lo stesso nome (anche solo per maiuscole), e lo scopre solo
 * a upload finito: un file già scelto, o ripetuto nella stessa scelta, si tiene una volta sola. */
function withoutRepeated(chosen: File[], current: File[]) {
  const names = new Set(current.map((file) => file.name.toLowerCase()))
  const fresh: File[] = []
  const repeated: string[] = []
  for (const file of chosen) {
    const name = file.name.toLowerCase()
    if (names.has(name)) repeated.push(file.name)
    else {
      names.add(name)
      fresh.push(file)
    }
  }
  return { fresh, repeated }
}

const repeatedNotice = (repeated: string[]) =>
  repeated.length === 0 ? null
    : repeated.length === 1 ? `${repeated[0]} è già nell'elenco: l'ho aggiunto una volta sola.`
      : `${repeated.join(', ')} sono già nell'elenco: li ho aggiunti una volta sola.`

const field =
  'mt-1.5 block min-h-10 w-full rounded-md border bg-card p-2 text-body text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring'
const labelText = 'min-w-0 flex-1 text-meta text-muted-foreground'

/**
 * Popup Nuova lezione (4.2.5 con wireframe RT-import.html):
 * - Riquadro unico che accetta audio e materiali (e zip) separandoli automaticamente.
 * - Righe audio numerate riordinabili con maniglia e tastiera (AudioOrder).
 * - Miniature dei materiali: un clic apre sotto il riquadro modalità, uso e pagine del file.
 *   Senza audio c'è sempre una guida (il primo documento con testo, o quello scelto).
 * - Ore del giorno dal calendario (GET /calendar/day) come scelte rapide; matita per i campi a mano.
 * - Menu materie da GET /subjects.
 */
export type NewLessonDialogProps = {
  open: boolean
  onClose: () => void
  initialDate?: string
  initialSlotKey?: string
  initialFiles?: File[]
  initialJob?: Schemas['Job']
}

export function NewLessonDialog({
  open,
  onClose,
  initialDate,
  initialSlotKey,
  initialFiles,
  initialJob,
}: NewLessonDialogProps) {
  const original = initialJob?.payload as { options?: Record<string, string | boolean>; audio?: string[]; inputs?: string[]; materiali?: string[]; text?: string; appunti?: string; run?: boolean } | undefined
  const options = original?.options
  const navigate = useNavigate()
  const client = useQueryClient()
  const lessons = useLessons()
  // Il caricamento sta nella coda (lib/uploadQueue): chiudendo la finestra continua.
  const [uploadId, setUploadId] = useState<string | null>(null)
  const upload = useUpload(uploadId)
  const [recreating, setRecreating] = useState(false)
  const [uploadError, setUploadError] = useState<unknown>(null)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const input = useRef<HTMLInputElement>(null)
  const materialsInput = useRef<HTMLInputElement>(null)
  const listId = useId()

  const [audioFiles, setAudioFiles] = useState<File[]>([])
  const [materialOptions, setMaterialOptions] = useState<Record<string, SourceOptions>>({})
  const [openMaterial, setOpenMaterial] = useState<string | null>(null)
  const [materialFiles, setMaterialFiles] = useState<File[]>([])
  const [zipFiles, setZipFiles] = useState<File[]>([])
  const [selectedPrimaryMaterialName, setPrimaryMaterialName] = useState<string | null>(null)
  const [sourceDefaults] = useSourceDefaults()
  const facts = useQueries({
    queries: materialFiles.map((file) => ({
      queryKey: ['file-facts', file.name, file.size, file.lastModified],
      queryFn: () => fileFacts(file),
      staleTime: Infinity,
      retry: false,
    })),
  })
  const hasAudio = audioFiles.length > 0
  // Scelte dell'utente o, finché non tocca nulla, i default dal tipo di file (e dall'archivio).
  const chosenOptions = (file: File, i: number): SourceOptions => {
    const known = facts[i]?.data
    return materialOptions[file.name] ?? {
      ...defaultOptions(file.name, sourceDefaults, known?.estrai),
      pagine: known?.entry?.da_continuare?.replace('–', '-') ?? null,
    }
  }
  const withText = (file: File, i: number) => chosenOptions(file, i).estrai !== 'solo_immagini'
  // Senza registrazione c'è sempre una guida: quella scelta o il primo documento con testo.
  const primaryMaterialName = hasAudio
    ? null
    : (materialFiles.find((file, i) => file.name === selectedPrimaryMaterialName && withText(file, i))
      ?? materialFiles.find(withText))?.name ?? null
  const optionsOf = (file: File, i: number): SourceOptions => {
    const chosen = chosenOptions(file, i)
    const uso = chosen.estrai === 'solo_immagini' ? 'contesto'
      : file.name === primaryMaterialName ? 'guida' : chosen.uso === 'guida' ? 'contesto' : chosen.uso
    return { ...chosen, uso }
  }
  const updateMaterial = (file: File, i: number, patch: SourceOptions) => {
    if (patch.uso === 'guida') setPrimaryMaterialName(file.name)
    setMaterialOptions((previous) => ({ ...previous, [file.name]: { ...optionsOf(file, i), ...patch } }))
  }
  const [manualMode, setManualMode] = useState(!!initialJob)
  const [selectedKey, setSelectedKey] = useState<string | null>(initialSlotKey ?? null)

  const [dragging, setDragging] = useState(false)
  const [materia, setMateria] = useState(String(options?.materia ?? ''))
  const [argomenti, setArgomenti] = useState(String(options?.argomenti ?? ''))
  const [conflict, setConflict] = useState<{ lesson_id?: number; titolo: string } | null>(() => (initialJob?.result as { details?: { lesson_id?: number; titolo: string } })?.details ?? null)
  const clearConflict = () => { setConflict(null); setUploadError(null) }
  const [docente, setDocente] = useState(String(options?.docente ?? ''))
  const [date, setDate] = useState(() => initialDate ?? String(options?.date ?? today()))
  const [time, setTime] = useState(String(options?.ora ?? ''))
  const [soloChosen, setSolo] = useState(!!initialJob && (initialJob.type === 'ingest_audio' || original?.run === false))
  // Senza registrazione non c'è niente da trascrivere: l'opzione si spegne da sola.
  const solo = soloChosen && (audioFiles.length > 0 || !!initialJob)
  const [review, setReview] = useState(!!options?.with_review)
  const [enrichment, setEnrichment] = useState(!!options?.with_enrichment)
  const [unisciAudio, setUnisciAudio] = useState(true)
  const [problem, setProblem] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [zipJob, setZipJob] = useState<string | null>(null)
  // Gli ZIP dell'ultimo invio: per una lezione già presente si rimandano con la scelta.
  const [sentZips, setSentZips] = useState<File[]>([])
  const openedJob = useRef<string | null>(null)
  const job = useJobStatus(zipJob)
  const result = job.data?.state === 'succeeded' ? (job.data.result as ZipImportResult | null) : null

  const kind = zipJob
    ? 'zip'
    : zipFiles.length > 0
      ? 'zip'
      : audioFiles.length > 0 || materialFiles.length > 0
        ? 'audio'
        : null

  const zipFinished = !!zipJob && jobFinished(job.data)
  const busy =
    recreating || (!!upload && isUploadActive(upload)) || (!!zipJob && !job.isError && !jobFinished(job.data))

  const subjectsQuery = useSubjects()
  const subjects = Array.isArray(subjectsQuery.data)
    ? subjectsQuery.data.map((s) => s.nome)
    : [...new Set((lessons.data ?? []).map((l) => l.materia).filter(Boolean))].sort()
  const teachers = useTeacherSuggestions(materia)

  const calendarDayQuery = useQuery({
    queryKey: calendarKeys.day(date),
    queryFn: () => calendarApi.getDay(date),
    enabled: open && !!date,
  })
  const hours = useMemo(
    () => (Array.isArray(calendarDayQuery.data?.hours) ? calendarDayQuery.data.hours : []),
    [calendarDayQuery.data],
  )

  // La scelta si confronta per chiave (tpl_N/ovr_N): dopo un nuovo fetch gli oggetti cambiano.
  const selectedSlot = hours.find((h) => h.key === selectedKey && !h.is_recorded && h.status !== 'annullata') ?? null
  // Tutte registrate: niente da scegliere, restano i campi a mano.
  const allRecorded = hours.length > 0 && hours.every((h) => h.is_recorded)

  // Selezione automatica dello slot al cambio data o al caricamento ore
  useEffect(() => {
    if (manualMode || hours.length === 0) return
    if (selectedKey) {
      const match = hours.find((h) => h.key === selectedKey && !h.is_recorded && h.status !== 'annullata')
      if (match && !materia) {
        // oxlint-disable-next-line react/set-state-in-effect
        setMateria(match.materia)
        setDocente(match.docente ?? '')
        setTime(match.start_time)
      }
      return
    }
    const pick = pickSlot(hours, date)
    if (!pick) return
    // oxlint-disable-next-line react/set-state-in-effect
    setSelectedKey(pick.key)
    setMateria(pick.materia)
    setDocente(pick.docente ?? '')
    setTime(pick.start_time)
  }, [hours, manualMode, selectedKey, date, materia])

  const choose = useCallback(
    (chosen: File[]) => {
      if (busy || chosen.length === 0) return
      const zipsFound = chosen.filter(isZip)
      if (zipsFound.length > 0) {
        if (zipsFound.length !== chosen.length) {
          setProblem('Scegli o solo file audio/materiali o solo pacchetti .zip.')
          return
        }
        setZipFiles(zipsFound)
        setNotice(null)
        setAudioFiles([])
        setMaterialFiles([])
        setProblem(null)
        setZipJob(null)
        setUploadError(null)
        return
      }

      const unsupported = chosen.find((f) => !isAudioFile(f) && !isMaterialFile(f) && !isZip(f))
      if (unsupported) {
        setProblem(
          `Formato non supportato: ${unsupported.name}. Usa ${AUDIO_EXTENSIONS.join(', ')} o ${MATERIAL_EXTENSIONS.join(', ')}.`,
        )
        return
      }

      const { fresh, repeated } = withoutRepeated(chosen, [...audioFiles, ...materialFiles])
      const auds = fresh.filter(isAudioFile)
      const mats = fresh.filter(isMaterialFile)

      // Ordinamento di partenza: data di modifica del file, poi per nome
      const sortedAuds = [...auds].sort(
        (a, b) => a.lastModified - b.lastModified || a.name.localeCompare(b.name),
      )

      setZipFiles([])
      setAudioFiles((prev) => [...prev, ...sortedAuds])
      setMaterialFiles((prev) => [...prev, ...mats])
      setProblem(null)
      setNotice(repeatedNotice(repeated))
      setZipJob(null)
      setUploadError(null)
    },
    [busy, audioFiles, materialFiles],
  )

  const initialFilesHandled = useRef(false)
  useEffect(() => {
    if (!initialFilesHandled.current && initialFiles && initialFiles.length > 0) {
      initialFilesHandled.current = true
      choose(initialFiles)
    }
  }, [initialFiles, choose])

  const chooseAdditionalMaterials = (chosen: File[]) => {
    if (busy || chosen.length === 0) return
    const { fresh, repeated } = withoutRepeated(chosen.filter(isMaterialFile), [...audioFiles, ...materialFiles])
    setMaterialFiles((prev) => [...prev, ...fresh])
    setNotice(repeatedNotice(repeated))
  }

  // Togliendo la guida passa al primo documento con testo rimasto (primaryMaterialName).
  const removeMaterial = (index: number) => {
    const name = materialFiles[index]?.name
    setMaterialFiles(materialFiles.filter((_, i) => i !== index))
    setMaterialOptions(({ [name]: _removed, ...rest }) => rest)
    setOpenMaterial(null)
  }

  const clear = () => {
    setNotice(null)
    setAudioFiles([])
    setMaterialFiles([])
    setZipFiles([])
    setPrimaryMaterialName(null)
    setMaterialOptions({})
    setUnisciAudio(true)
    setProblem(null)
    setZipJob(null)
  }

  const changeDay = (delta: number) => {
    const parts = date.split('-').map(Number)
    const d = new Date(parts[0], parts[1] - 1, parts[2] + delta)
    const newDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    setDate(newDate)
    clearConflict()
    setSelectedKey(null)
  }

  const handleSelectSlot = (h: CalendarEventView) => {
    if (h.is_recorded || h.status === 'annullata') return
    setSelectedKey(h.key)
    setMateria(h.materia)
    setDocente(h.docente ?? '')
    setTime(h.start_time)
  }

  const finished = useCallback(() => {
    invalidateAfterJob(client)
  }, [client])

  const imported =
    result?.results.filter((item) => item.status === 'imported' && item.lesson_id != null) ?? []
  const conflicts = result?.results.filter((item) => item.status === 'conflict') ?? []
  const alreadyPresent =
    (result?.results.filter((item) => item.code === 'duplicate_lesson').length ?? 0) + conflicts.length
  const rejected =
    result?.results.filter(
      (item) => item.status === 'rejected' && item.code !== 'duplicate_lesson',
    ).length ?? 0
  const only =
    result && imported.length === 1 && result.rejected === 0 && conflicts.length === 0 ? imported[0].lesson_id : null

  useEffect(() => {
    if (only == null || !zipJob || openedJob.current === zipJob) return
    openedJob.current = zipJob
    onClose()
    navigate(`/lezioni/${only}`)
  }, [only, zipJob, onClose, navigate])

  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || zipJob) return

    if (kind === 'zip') {
      sendZips(zipFiles)
      return
    }

    if (initialJob) {
      setUploadError(null)
      setRecreating(true)
      void unwrap(api.POST('/api/v1/jobs/{job_id}/recreate-lesson', { params: { path: { job_id: initialJob.id } }, body: { date, materia, argomenti, docente, ora: time } })).then(accepted => {
        invalidateAfterJob(client)
        onClose()
        navigate(`/lezioni/nuova/${accepted.job_id}`)
      }).catch(showError).finally(() => setRecreating(false))
      return
    }
    if (problem) return

    if (audioFiles.length === 0 && materialFiles.length === 0) {
      setProblem('Scegli almeno un file audio o un materiale.')
      return
    }

    if (!materia.trim()) {
      setProblem('Indica la materia.')
      return
    }

    setProblem(null)

    const chosenSlot = manualMode ? null : selectedSlot

    const input: NewLesson = {
      files: audioFiles,
      materiali: materialFiles.length > 0 ? materialFiles : undefined,
      opzioni: Object.fromEntries(materialFiles.map((file, i) => {
        const { pagine, ...chosen } = optionsOf(file, i)
        return [file.name, hasPages(file.name) && pagine ? { ...chosen, pagine } : chosen]
      })),
      principale: primaryMaterialName ?? undefined,
      unisci: audioFiles.length > 1 ? unisciAudio : undefined,
      calendar_entry_id: chosenSlot?.key,
      calendar_date: chosenSlot ? date : undefined,
      date,
      materia: materia.trim(),
      argomenti,
      docente: docente.trim(),
      ora: time,
      run: !solo,
      mock: false,
      auto_accept: false,
      with_review: !solo && review,
      with_enrichment: !solo && enrichment,
    }
    startUpload(
      `${materia.trim()} · ${date}`,
      [...audioFiles, ...materialFiles],
      (onProgress, signal) => sendLesson(input, onProgress, signal),
      (accepted) => {
        onClose()
        navigate(`/lezioni/nuova/${accepted.job_id}`)
      },
    )
  }

  /** Invia gli ZIP; con decisions sono le scelte per le lezioni già presenti del primo invio. */
  function sendZips(files: File[], decisions?: ZipImportDecision[]) {
    startUpload(
      files.length === 1 ? files[0].name : `${files.length} pacchetti .zip`,
      files,
      (onProgress, signal) => sendLessonZips(files, onProgress, signal, decisions),
      (accepted) => {
        setSentZips(files)
        setZipJob(accepted.job_id)
        setZipFiles([])
      },
    )
  }

  function showError(reason: unknown) {
    setUploadError(reason)
    if (reason instanceof ApiError && reason.code === 'lesson_exists') {
      setConflict(reason.details as { lesson_id?: number; titolo: string })
      setManualMode(true)
    }
  }

  /** Accoda l'invio. A finestra ancora aperta si prosegue come prima (pagina del job, esito
   * dello zip); a finestra chiusa il job compare in Job e gli errori restano nella sua riga. */
  function startUpload(
    label: string,
    files: File[],
    send: UploadSend<{ job_id: string }>,
    accepted: (value: { job_id: string }) => void,
  ) {
    setUploadError(null)
    const { id, done } = enqueueUpload(label, files, send)
    setUploadId(id)
    done.then(
      (value) => {
        invalidateAfterJob(client)
        if (!mounted.current) return
        setUploadId(null)
        accepted(value)
      },
      (reason: unknown) => {
        if (!mounted.current) return
        setUploadId(null)
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        // L'errore si legge qui: la riga fallita non serve anche in Job.
        cancelUpload(id)
        showError(reason)
      },
    )
  }

  const percent = upload?.total ? Math.round((upload.loaded / upload.total) * 100) : null
  const error = uploadError
  const errorText =
    error instanceof ApiError && error.code === 'payload_too_large'
      ? `${error.message} Dividi l'audio in più file più piccoli.`
      : error
        ? errorMessage(error)
        : null

  const totalAudioBytes = audioFiles.reduce((sum, f) => sum + f.size, 0)
  const totalZipBytes = zipFiles.reduce((sum, f) => sum + f.size, 0)

  // Composizione della frase dinamica
  const steps: string[] = [
    audioFiles.length === 0 && materialFiles.length > 0
      ? 'lettura dei materiali'
      : 'trascrizione',
    'scaletta',
    materialFiles.length > 0 ? 'rielaborazione con i materiali' : 'rielaborazione',
  ]
  if (!solo && review) steps.push('revisione')
  if (!solo && enrichment) steps.push('arricchimento')
  if (!solo && materialFiles.some((file, i) => optionsOf(file, i).estrai !== 'testo')) {
    steps.push('immagini nelle unità')
  }
  const stepsList =
    steps.length > 1 ? `${steps.slice(0, -1).join(', ')} e ${steps[steps.length - 1]}` : steps[0]
  let sentence = solo ? "Dopo l'importazione: solo trascrizione" : `Dopo l'importazione: ${stepsList}`
  if (!manualMode && selectedSlot) {
    sentence += ` · collegata a ${selectedSlot.materia} delle ${selectedSlot.start_time}`
  }

  const anyFiles = !!initialJob || audioFiles.length > 0 || materialFiles.length > 0 || zipFiles.length > 0
  const showSlots = hours.length > 0 && !manualMode && kind !== 'zip'

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Nuova lezione"
      testId="new-lesson"
      className="w-[min(680px,calc(100vw-32px))]"
    >
      <form onSubmit={submit} aria-label="Nuova lezione" noValidate>
        {/* Input file principale (audio, zip, o materiali) */}
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={['audio/*', '.zip', ...MATERIAL_EXTENSIONS, ...AUDIO_EXTENSIONS].join(',')}
          aria-label="Audio o pacchetto della lezione"
          onChange={(event) => {
            choose(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />

        {/* Input file dedicato per aggiungere materiali secondari */}
        <input
          ref={materialsInput}
          type="file"
          multiple
          hidden
          accept={MATERIAL_EXTENSIONS.join(',')}
          aria-label="Altri documenti"
          onChange={(event) => {
            chooseAdditionalMaterials(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />

        {/* 1. Riquadro drop iniziale (nessun file) */}
        {!anyFiles ? (
          <div
            role="button"
            tabIndex={0}
            aria-label={DROP_LABEL}
            data-testid="drop-zone"
            onClick={() => input.current?.click()}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                input.current?.click()
              }
            }}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              choose(Array.from(event.dataTransfer.files))
            }}
            className={cn(
              'my-4 flex min-h-[110px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-4 text-center text-muted-foreground',
              'hover:border-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
              dragging && 'border-foreground bg-muted',
            )}
          >
            <Upload className="size-[18px]" aria-hidden />
            <span className="text-meta">{DROP_TEXT}</span>
          </div>
        ) : initialJob ? (
          <ul className="my-3 text-meta" aria-label="Fonti già caricate">{[...(original?.audio ?? original?.inputs ?? []), ...(original?.materiali ?? [])].map(path => <li key={path}>{path.split(/[\\/]/).pop()}</li>)}{(original?.text || original?.appunti) && <li>Appunti</li>}</ul>
        ) : kind === 'zip' ? (
          /* 2. Pacchetto zip selezionato */
          <div
            className="my-4 flex min-h-[110px] items-center justify-center gap-2.5 rounded-lg border border-dashed px-4 py-3 text-foreground"
            data-testid="chosen-files"
            data-kind="zip"
          >
            <Archive className="size-[18px] shrink-0" aria-hidden />
            <span className="min-w-0 text-meta [overflow-wrap:anywhere]">
              {zipFiles.length === 1
                ? zipFiles[0].name
                : `${zipFiles.length} file · ${formatBytes(totalZipBytes)}`}
            </span>
            <IconButton label="Rimuovi" icon={X} disabled={busy} onClick={clear} />
          </div>
        ) : (
          /* 3. Audio e/o Materiali selezionati */
          <div
            className="my-4 flex flex-col gap-3 rounded-lg border border-dashed p-3 text-foreground"
            data-testid="chosen-files"
            data-kind="audio"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault()
              choose(Array.from(event.dataTransfer.files))
            }}
          >
            {/* Sezione Audio */}
            {audioFiles.length > 1 ? (
              <div>
                <AudioOrder files={audioFiles} disabled={busy} onChange={setAudioFiles} />
                <div className="-mt-2 mb-1 flex items-center justify-between gap-2 text-meta text-muted-foreground">
                  <span className="flex items-center gap-1.5 min-w-0 truncate">
                    <FileAudio className="size-4 shrink-0" aria-hidden />
                    <span className="truncate">
                      {audioFiles.length} parti · {formatBytes(totalAudioBytes)} ·{' '}
                      {unisciAudio
                        ? "diventano un'unica registrazione, in quest'ordine"
                        : `restano ${audioFiles.length} fonti separate`}
                    </span>
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <MergeAudioToggle merged={unisciAudio} disabled={busy} onChange={setUnisciAudio} />
                    <IconButton
                      label="Rimuovi tutti gli audio"
                      icon={X}
                      disabled={busy}
                      onClick={() => setAudioFiles([])}
                    />
                  </div>
                </div>
              </div>
            ) : audioFiles.length === 1 ? (
              <div className="flex items-center justify-between gap-2 rounded-md border bg-card px-3 py-2 text-meta">
                <div className="flex items-center gap-2 min-w-0">
                  <FileAudio className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate font-medium">{audioFiles[0].name}</span>
                  <span className="text-muted-foreground">{formatBytes(audioFiles[0].size)}</span>
                </div>
                <IconButton
                  label="Rimuovi audio"
                  icon={X}
                  disabled={busy}
                  onClick={() => setAudioFiles([])}
                />
              </div>
            ) : null}

            {/* Sezione Materiali */}
            {materialFiles.length > 0 ? (
              <div className="flex flex-col gap-1.5" data-testid="materials-container">
                <div className="flex flex-wrap items-end gap-2" data-testid="materials-list">
                  {materialFiles.map((m, i) => {
                    const isOpen = openMaterial === m.name
                    return (
                      <div
                        key={`${m.name}-${i}`}
                        className="relative flex w-16 flex-col gap-1 text-[11px] text-muted-foreground"
                        data-testid={`material-thumb-${i}`}
                      >
                        <button
                          type="button"
                          aria-label={`Opzioni ${m.name}`}
                          aria-pressed={isOpen}
                          aria-expanded={isOpen}
                          onClick={() => setOpenMaterial(isOpen ? null : m.name)}
                          className={cn(
                            'relative flex h-12 w-16 items-center justify-center overflow-hidden rounded-lg bg-card p-1 shadow-xs',
                            isOpen ? 'border-2 border-link' : 'border border-border hover:border-foreground',
                          )}
                        >
                          <SourceFileIcon name={m.name} className="size-6 text-muted-foreground" />
                          <SourceBadges options={optionsOf(m, i)} />
                        </button>
                        {facts[i]?.data?.entry && <KnownBadge />}
                        <span className="truncate text-center" title={m.name}>
                          {m.name}
                        </span>
                      </div>
                    )
                  })}
                  <button
                    type="button"
                    className="mb-4 flex size-12 items-center justify-center rounded-lg border border-dashed border-border text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
                    aria-label="Aggiungi materiali"
                    onClick={() => materialsInput.current?.click()}
                    data-testid="add-materials-btn"
                  >
                    <Plus className="size-4" />
                  </button>
                </div>
                {materialFiles.map((m, i) => {
                  if (m.name !== openMaterial) return null
                  const current = optionsOf(m, i)
                  const reasons = sourceReasons({ name: m.name, options: current, hasAudio, isGuide: m.name === primaryMaterialName })
                  const total = facts[i]?.data?.pagine_totali ?? null
                  return (
                    <div key={m.name} data-testid="source-layer"
                      className="-mx-3 -mb-3 mt-1 flex flex-wrap items-center gap-3 rounded-b-lg border-t bg-muted/40 px-3 py-2 sm:flex-nowrap">
                      <ExtractOptions value={current.estrai ?? 'immagini'} unavailable={reasons.extract}
                        onChange={(estrai) => updateMaterial(m, i, { estrai })} />
                      <UseOptions value={current.uso ?? 'contesto'} unavailable={reasons.use} off={reasons.off}
                        onChange={(uso) => updateMaterial(m, i, { uso })} />
                      {hasPages(m.name) && !textOnly(m.name) && total !== 1 && (
                        <PagesOptions value={current.pagine} total={total}
                          onChange={(pagine) => updateMaterial(m, i, { pagine })} />
                      )}
                      <IconButton label="Elimina fonte" icon={Trash2} disabled={busy} className="ml-auto"
                        onClick={() => removeMaterial(i)} />
                    </div>
                  )
                })}
              </div>
            ) : audioFiles.length > 0 ? (
              <div className="flex items-center">
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded-md border border-dashed px-2.5 py-1 text-meta text-muted-foreground hover:border-foreground hover:text-foreground"
                  aria-label="Slide, PDF o foto della lezione"
                  onClick={() => materialsInput.current?.click()}
                  data-testid="add-materials-btn"
                >
                  <Plus className="size-3.5" />
                  Materiali
                </button>
              </div>
            ) : null}
          </div>
        )}

        {/* 4. Calendario e campi manuali */}
        {kind !== 'zip' && (
          <>
            {/* Scelte rapide dal calendario */}
            {showSlots && (
              <div className="mb-3 flex flex-col gap-2" data-testid="calendar-slots-section">
                <div className="flex items-center justify-between text-meta text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <IconButton
                      icon={ChevronLeft}
                      label="Giorno prima"
                      onClick={() => changeDay(-1)}
                      data-testid="calendar-prev-day"
                    />
                    <span className="font-semibold text-foreground px-1">
                      {formatDayLabel(date)}
                    </span>
                    <IconButton
                      icon={ChevronRight}
                      label="Giorno dopo"
                      onClick={() => changeDay(1)}
                      data-testid="calendar-next-day"
                    />
                  </div>
                  <IconButton
                    icon={Pencil}
                    label="Scrivi a mano"
                    active={manualMode}
                    onClick={() => setManualMode(!manualMode)}
                    data-testid="manual-fields-toggle"
                  />
                </div>

                <div className="flex flex-wrap gap-2" data-testid="calendar-slots-list">
                  {hours.map((h, i) => {
                    const isSelected = selectedSlot?.key === h.key
                    return (
                      <button
                        key={h.key}
                        type="button"
                        disabled={h.is_recorded || h.status === 'annullata'}
                        onClick={() => handleSelectSlot(h)}
                        className={cn(
                          'flex items-center gap-2 rounded-lg bg-card text-left text-meta transition-all min-w-0',
                          isSelected
                            ? 'border-2 border-link bg-primary/20 px-[9px] py-[5px]'
                            : 'border border-border px-2.5 py-1.5',
                          (h.is_recorded || h.status === 'annullata') && 'opacity-50 cursor-not-allowed',
                        )}
                        aria-label={h.status === 'annullata' ? `${h.materia} - Ora annullata` : h.is_recorded ? `${h.materia} - Già registrata` : `${h.materia} ${h.start_time}-${h.end_time}${h.docente ? ` - ${h.docente}` : ''}`}
                        data-testid={`calendar-slot-${i}`}
                      >
                        <span
                          className={cn(
                            'w-1 self-stretch rounded-full',
                            isSelected ? 'bg-link' : 'bg-muted-foreground/30',
                          )}
                        />
                        <div className="flex flex-col leading-tight">
                          <span className="font-semibold text-foreground text-xs">{h.materia}</span>
                          <span className="text-[11px] text-muted-foreground tabular-nums">
                            {h.start_time}–{h.end_time}
                          </span>
                        </div>
                        {h.is_recorded && (
                          <Check className="size-3.5 text-emerald-600 shrink-0 ml-1" />
                        )}
                        {!h.is_recorded && h.status === 'annullata' && (
                          <Ban className="size-3.5 text-muted-foreground shrink-0 ml-1" aria-hidden />
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Campi manuali */}
            <div
              className={cn(
                'mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4',
                showSlots && !allRecorded && 'hidden',
              )}
              data-testid="manual-fields"
            >
              <label className={labelText}>
                Materia
                <input
                  className={cn(field, conflict && 'border-danger')}
                  list={`${listId}-materie`}
                  value={materia}
                  required
                  disabled={busy}
                  aria-invalid={!!conflict}
                  onChange={(e) => { setMateria(e.target.value); clearConflict() }}
                />
              </label>
              <label className={labelText}>
                Docente
                <input
                  className={field}
                  list={`${listId}-docenti`}
                  value={docente}
                  disabled={busy}
                  onChange={(e) => setDocente(e.target.value)}
                />
              </label>
              <label className={labelText}>
                Data{date === today() && ' · oggi'}
                <input
                  className={cn(field, conflict && 'border-danger')}
                  type="date"
                  value={date}
                  required
                  disabled={busy}
                  aria-invalid={!!conflict}
                  onChange={(e) => { setDate(e.target.value); clearConflict() }}
                />
              </label>
              <label className={labelText}>
                Ora
                <input
                  className={field}
                  type="time"
                  value={time}
                  disabled={busy}
                  onChange={(e) => setTime(e.target.value)}
                />
              </label>
              <label className={labelText}>Argomenti
                <input className={cn(field, conflict && 'border-danger')} value={argomenti} disabled={busy} aria-invalid={!!conflict} onChange={e => { setArgomenti(e.target.value); clearConflict() }} />
              </label>
              <datalist id={`${listId}-materie`}>
                {subjects.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
              <datalist id={`${listId}-docenti`}>
                {teachers.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </div>

            <p className="mb-3 text-meta text-muted-foreground" data-testid="pipeline-sentence">
              {sentence}
            </p>
          </>
        )}

        {problem && <Alert tone="danger">{problem}</Alert>}
        {notice && !problem && <Alert tone="warning">{notice}</Alert>}
        {conflict && <Alert tone="danger">Esiste già: <Link to={`/lezioni/${conflict.lesson_id}`} target="_blank" rel="noopener" className="underline">{conflict.titolo}</Link></Alert>}
        {errorText && !conflict && <Alert tone="danger">{errorText}</Alert>}
        {upload && isUploadActive(upload) && (
          <div className="my-3 flex flex-col gap-1.5" data-testid="upload-status">
            {upload.state === 'queued' ? (
              <p className="text-meta text-muted-foreground">In coda: parte quando finisce il caricamento in corso.</p>
            ) : (
              <ProgressBar value={percent} label="Caricamento" className="h-1.5" />
            )}
            <p className="flex flex-wrap items-center gap-x-2 text-meta text-muted-foreground">
              <span>Puoi chiudere la finestra: il caricamento continua e lo segui in Job. Tieni aperta la scheda di RT finché non finisce.</span>
              <button type="button" className="underline" onClick={() => cancelUpload(upload.id)}>
                Annulla il caricamento
              </button>
            </p>
          </div>
        )}
        {zipJob && (
          <div className="my-3">
            <JobProgress
              jobId={zipJob}
              label="Importazione del pacchetto"
              onFinished={finished}
            />
          </div>
        )}
        {result && only == null && (
          <div className="my-3">
            <p className="text-meta font-semibold" data-testid="import-summary">
              {result.imported} importate, {alreadyPresent} già presenti, {rejected} rifiutate
            </p>
            <ul className="my-3 text-meta" aria-label="Esito dell'importazione">
              {result.results.map((item, index) => (
                <li key={index}>
                  {item.file}:{' '}
                  {item.status === 'imported' ? (
                    <>
                      importata
                      {item.lesson_id != null && (
                        <>
                          {' '}
                          ·{' '}
                          <Link
                            className="underline"
                            to={`/lezioni/${item.lesson_id}`}
                            onClick={onClose}
                          >
                            apri
                          </Link>
                        </>
                      )}
                    </>
                  ) : item.status === 'conflict' ? (
                    'già presente · scegli qui sotto'
                  ) : (
                    `${item.code === 'duplicate_lesson' ? 'già presente' : 'rifiutata'} · ${item.reason}`
                  )}
                  {item.replaced_lesson_id != null && ' (ha rimpiazzato la tua)'}
                </li>
              ))}
            </ul>
            {conflicts.length > 0 && (
              <ImportConflicts
                key={zipJob}
                items={conflicts}
                files={sentZips}
                onSubmit={(files, decisions) => {
                  setZipJob(null)
                  sendZips(files, decisions)
                }}
              />
            )}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          {zipFinished ? (
            <Button onClick={onClose}>Chiudi</Button>
          ) : (
            <Button
              type="submit"
              className={cn(
                kind === 'zip'
                  ? 'h-10 px-4 font-semibold'
                  : 'size-11 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90',
              )}
              disabled={busy || !!zipJob}
              aria-label={kind === 'zip' ? 'Importa' : 'Avvia'}
              title={kind === 'zip' ? 'Importa' : 'Avvia'}
            >
              {kind === 'zip' ? (
                <Upload aria-hidden />
              ) : (
                <Play className="size-5 fill-current" aria-hidden />
              )}
              {kind === 'zip' && <span>Importa</span>}
            </Button>
          )}

          {kind !== 'zip' && !initialJob && (
            <div
              className="flex items-center gap-1.5"
              role="group"
              aria-label="Fasi dopo l'importazione"
            >
              <IconButton
                label="Solo trascrizione"
                icon={FileText}
                aria-pressed={solo}
                active={solo}
                unavailable={busy ? 'importazione in corso' : !hasAudio ? 'serve una registrazione' : null}
                onClick={() => setSolo(!solo)}
              />
              <IconButton
                label="Revisione"
                icon={ShieldCheck}
                aria-pressed={review}
                active={review && !solo}
                unavailable={busy ? 'importazione in corso' : solo ? 'non con Solo trascrizione' : null}
                onClick={() => setReview(!review)}
              />
              <IconButton
                label="Arricchimento"
                icon={Image}
                aria-pressed={enrichment}
                active={enrichment && !solo}
                unavailable={busy ? 'importazione in corso' : solo ? 'non con Solo trascrizione' : null}
                onClick={() => setEnrichment(!enrichment)}
              />
            </div>
          )}
        </div>
      </form>
    </Modal>
  )
}
