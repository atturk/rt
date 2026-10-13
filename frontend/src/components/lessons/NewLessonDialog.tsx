import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  Check,
  ChevronLeft,
  ChevronRight,
  FileAudio,
  FileText,
  Image,
  Paperclip,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Star,
  Upload,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { useSubjects } from '@/api/subjects'
import { calendarApi, calendarKeys, type CalendarEventView } from '@/api/calendar'
import {
  invalidateAfterJob,
  useCreateLesson,
  useImportLessonZips,
  type ZipImportResult,
} from '@/api/jobs'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { JobProgress } from '@/components/JobProgress'
import { AudioOrder } from '@/components/lessons/AudioOrder'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
import { AUDIO_EXTENSIONS, formatBytes } from '@/lib/jobs'
import { cn } from '@/lib/utils'

const DROP_LABEL = "Trascina l'audio o il pacchetto della lezione, o fai clic"
const DROP_TEXT = "Trascina qui l'audio della lezione, slide, PDF o foto, oppure un pacchetto .zip. Clic per scegliere."

const MATERIAL_EXTENSIONS = [
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.tiff',
  '.bmp',
  '.gif',
]

function isAudioFile(file: File): boolean {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  return AUDIO_EXTENSIONS.includes(ext) || file.type.startsWith('audio/')
}

function isMaterialFile(file: File): boolean {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  return (
    MATERIAL_EXTENSIONS.includes(ext) ||
    file.type.startsWith('image/') ||
    file.type === 'application/pdf'
  )
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

const field =
  'mt-1.5 block min-h-10 w-full rounded-md border bg-card p-2 text-body text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring'
const labelText = 'min-w-0 flex-1 text-meta text-muted-foreground'

/**
 * Popup Nuova lezione (4.2.5 con wireframe RT-import.html):
 * - Riquadro unico che accetta audio e materiali (e zip) separandoli automaticamente.
 * - Righe audio numerate riordinabili con maniglia e tastiera (AudioOrder).
 * - Miniature dei materiali con stellina (senza audio) per il materiale principale.
 * - Ore del giorno dal calendario (GET /calendar/day) come scelte rapide; matita per i campi a mano.
 * - Graffetta per allegare i materiali alle unità (allega_materiali).
 * - Menu materie da GET /subjects.
 */
export function NewLessonDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const lessons = useLessons()
  const create = useCreateLesson()
  const zips = useImportLessonZips()
  const input = useRef<HTMLInputElement>(null)
  const materialsInput = useRef<HTMLInputElement>(null)
  const listId = useId()

  const [audioFiles, setAudioFiles] = useState<File[]>([])
  const [materialFiles, setMaterialFiles] = useState<File[]>([])
  const [zipFiles, setZipFiles] = useState<File[]>([])
  const [primaryMaterialName, setPrimaryMaterialName] = useState<string | null>(null)
  const [attachMaterials, setAttachMaterials] = useState(true)
  const [manualMode, setManualMode] = useState(false)
  const [selectedSlot, setSelectedSlot] = useState<CalendarEventView | null>(null)

  const [dragging, setDragging] = useState(false)
  const [materia, setMateria] = useState('')
  const [docente, setDocente] = useState('')
  const [date, setDate] = useState(today)
  const [time, setTime] = useState('')
  const [solo, setSolo] = useState(false)
  const [review, setReview] = useState(false)
  const [enrichment, setEnrichment] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [zipJob, setZipJob] = useState<string | null>(null)
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
    create.isPending || zips.isPending || (!!zipJob && !job.isError && !jobFinished(job.data))

  const subjectsQuery = useSubjects()
  const subjects = Array.isArray(subjectsQuery.data)
    ? subjectsQuery.data.map((s) => s.nome)
    : [...new Set((lessons.data ?? []).map((l) => l.materia).filter(Boolean))].sort()
  const teachers = [
    ...new Set((lessons.data ?? []).map((l) => l.docente?.trim()).filter(Boolean)),
  ].sort()

  const calendarDayQuery = useQuery({
    queryKey: calendarKeys.day(date),
    queryFn: () => calendarApi.getDay(date),
    enabled: open && !!date,
  })
  const hours = useMemo(
    () => (Array.isArray(calendarDayQuery.data?.hours) ? calendarDayQuery.data.hours : []),
    [calendarDayQuery.data],
  )

  // Selezione automatica dello slot al cambio data o al caricamento ore
  useEffect(() => {
    if (manualMode || hours.length === 0) return
    if (!selectedSlot) {
      const unrecorded = hours.filter((h) => !h.is_recorded)
      if (unrecorded.length > 0) {
        const pick = unrecorded[0]
        // oxlint-disable-next-line react/set-state-in-effect
        setSelectedSlot(pick)
        setMateria(pick.materia)
        setDocente(pick.docente ?? '')
        setTime(pick.start_time)
      }
    }
  }, [hours, manualMode, selectedSlot])

  const choose = (chosen: File[]) => {
    if (busy || chosen.length === 0) return
    const zipsFound = chosen.filter(isZip)
    if (zipsFound.length > 0) {
      if (zipsFound.length !== chosen.length) {
        setProblem('Scegli o solo file audio/materiali o solo pacchetti .zip.')
        return
      }
      setZipFiles(zipsFound)
      setAudioFiles([])
      setMaterialFiles([])
      setProblem(null)
      setZipJob(null)
      create.reset()
      zips.reset()
      return
    }

    const auds = chosen.filter(isAudioFile)
    const mats = chosen.filter(isMaterialFile)

    const unsupported = chosen.find((f) => !isAudioFile(f) && !isMaterialFile(f) && !isZip(f))
    if (unsupported) {
      setProblem(`Formato non supportato: ${unsupported.name}. Usa ${AUDIO_EXTENSIONS.join(', ')} o PDF/immagini.`)
      return
    }

    // Ordinamento di partenza: data di modifica del file, poi per nome
    const sortedAuds = [...auds].sort(
      (a, b) => a.lastModified - b.lastModified || a.name.localeCompare(b.name),
    )

    setZipFiles([])
    setAudioFiles((prev) => [...prev, ...sortedAuds])
    setMaterialFiles((prev) => {
      const combined = [...prev, ...mats]
      if (combined.length > 0) {
        setAttachMaterials(true)
        if (!primaryMaterialName) {
          setPrimaryMaterialName(combined[0].name)
        }
      }
      return combined
    })
    setProblem(null)
    setZipJob(null)
    create.reset()
  }

  const chooseAdditionalMaterials = (chosen: File[]) => {
    if (busy || chosen.length === 0) return
    const mats = chosen.filter(isMaterialFile)
    setMaterialFiles((prev) => {
      const combined = [...prev, ...mats]
      if (combined.length > 0) {
        setAttachMaterials(true)
        if (!primaryMaterialName) {
          setPrimaryMaterialName(combined[0].name)
        }
      }
      return combined
    })
  }

  const removeMaterial = (index: number) => {
    const toRemove = materialFiles[index]
    const updated = materialFiles.filter((_, i) => i !== index)
    setMaterialFiles(updated)
    if (primaryMaterialName === toRemove?.name) {
      setPrimaryMaterialName(updated[0]?.name ?? null)
    }
    if (updated.length === 0) {
      setAttachMaterials(false)
    }
  }

  const clear = () => {
    setAudioFiles([])
    setMaterialFiles([])
    setZipFiles([])
    setPrimaryMaterialName(null)
    setProblem(null)
    setZipJob(null)
  }

  const changeDay = (delta: number) => {
    const parts = date.split('-').map(Number)
    const d = new Date(parts[0], parts[1] - 1, parts[2] + delta)
    const newDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    setDate(newDate)
    setSelectedSlot(null)
  }

  const handleSelectSlot = (h: CalendarEventView) => {
    if (h.is_recorded) return
    setSelectedSlot(h)
    setMateria(h.materia)
    setDocente(h.docente ?? '')
    setTime(h.start_time)
  }

  const finished = useCallback(() => {
    invalidateAfterJob(client)
  }, [client])

  const imported =
    result?.results.filter((item) => item.status === 'imported' && item.lesson_id != null) ?? []
  const alreadyPresent =
    result?.results.filter((item) => item.code === 'duplicate_lesson').length ?? 0
  const rejected =
    result?.results.filter(
      (item) => item.status === 'rejected' && item.code !== 'duplicate_lesson',
    ).length ?? 0
  const only =
    result && imported.length === 1 && result.rejected === 0 ? imported[0].lesson_id : null

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
      zips.mutate(zipFiles, {
        onSuccess: (accepted) => {
          setZipJob(accepted.job_id)
          setZipFiles([])
        },
      })
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

    const chosenSlot = !manualMode && hours.length > 0 ? selectedSlot : null
    const slotEntryId = chosenSlot?.template_entry_id
      ? String(chosenSlot.template_entry_id)
      : chosenSlot?.override_id
        ? String(chosenSlot.override_id)
        : undefined

    create.mutate(
      {
        files: audioFiles,
        materiali: materialFiles.length > 0 ? materialFiles : undefined,
        principale:
          audioFiles.length === 0 && primaryMaterialName ? primaryMaterialName : undefined,
        allega_materiali: materialFiles.length > 0 ? attachMaterials : undefined,
        calendar_entry_id: slotEntryId,
        calendar_date: chosenSlot ? date : undefined,
        date,
        materia: materia.trim(),
        argomenti: '',
        docente: docente.trim(),
        ora: time,
        run: !solo,
        mock: false,
        auto_accept: false,
        with_review: !solo && review,
        with_enrichment: !solo && enrichment,
      },
      {
        onSuccess: (accepted) => {
          onClose()
          navigate(`/lezioni/nuova/${accepted.job_id}`)
        },
      },
    )
  }

  const upload = create.progress ?? zips.progress
  const percent = upload?.total ? Math.round((upload.loaded / upload.total) * 100) : null
  const error = create.error ?? zips.error
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
  if (!solo && materialFiles.length > 0 && attachMaterials) {
    steps.push('materiali allegati alle unità')
  }
  const stepsList =
    steps.length > 1 ? `${steps.slice(0, -1).join(', ')} e ${steps[steps.length - 1]}` : steps[0]
  let sentence = solo ? "Dopo l'importazione: solo trascrizione" : `Dopo l'importazione: ${stepsList}`
  if (!manualMode && selectedSlot && !selectedSlot.is_recorded) {
    sentence += ` · collegata a ${selectedSlot.materia} delle ${selectedSlot.start_time}`
  }

  const anyFiles = audioFiles.length > 0 || materialFiles.length > 0 || zipFiles.length > 0
  const showSlots = hours.length > 0 && !manualMode && kind !== 'zip'

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Nuova lezione"
      testId="new-lesson"
      className="w-[min(560px,calc(100vw-32px))]"
    >
      <form onSubmit={submit} aria-label="Nuova lezione" noValidate>
        {/* Input file principale (audio, zip, o materiali) */}
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={['audio/*', '.zip', '.pdf', 'image/*', ...AUDIO_EXTENSIONS].join(',')}
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
          accept=".pdf,image/*"
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
                <p className="-mt-2 mb-1 flex items-center justify-between text-meta text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <FileAudio className="size-4 shrink-0" aria-hidden />
                    <span>
                      {audioFiles.length} parti · {formatBytes(totalAudioBytes)} · diventano un'unica registrazione, in quest'ordine
                    </span>
                  </span>
                  <IconButton
                    label="Rimuovi tutti gli audio"
                    icon={X}
                    disabled={busy}
                    onClick={() => setAudioFiles([])}
                  />
                </p>
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
                    const isPrimary = primaryMaterialName === m.name
                    return (
                      <div
                        key={`${m.name}-${i}`}
                        className="group relative flex w-16 flex-col gap-1 text-[11px] text-muted-foreground"
                        data-testid={`material-thumb-${i}`}
                      >
                        <div className="relative flex h-12 w-16 items-center justify-center rounded-lg border border-border bg-card p-1 shadow-xs overflow-hidden">
                          {m.type.startsWith('image/') ? (
                            <Image className="size-6 text-muted-foreground" aria-hidden />
                          ) : (
                            <FileText className="size-6 text-muted-foreground" aria-hidden />
                          )}
                          {audioFiles.length === 0 && (
                            <button
                              type="button"
                              className={cn(
                                'absolute top-1 left-1 size-5 rounded-full bg-background/90 flex items-center justify-center transition-colors',
                                isPrimary
                                  ? 'text-amber-500'
                                  : 'text-muted-foreground hover:text-foreground',
                              )}
                              aria-label={
                                isPrimary
                                  ? 'Materiale principale: fa da filo della lezione'
                                  : 'Usa come materiale principale'
                              }
                              aria-pressed={isPrimary}
                              onClick={(e) => {
                                e.stopPropagation()
                                setPrimaryMaterialName(m.name)
                              }}
                              data-testid={`material-star-${i}`}
                            >
                              <Star className={cn('size-3.5', isPrimary && 'fill-current')} />
                            </button>
                          )}
                        </div>
                        <span className="truncate text-center" title={m.name}>
                          {m.name}
                        </span>
                        <button
                          type="button"
                          className="absolute -top-1.5 -right-1.5 hidden size-5 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-xs hover:text-foreground group-hover:flex group-focus-within:flex"
                          aria-label={`Togli ${m.name}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            removeMaterial(i)
                          }}
                          data-testid={`material-remove-${i}`}
                        >
                          <X className="size-3" />
                        </button>
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
                {audioFiles.length === 0 && primaryMaterialName && (
                  <div
                    className="mt-1 flex items-center gap-1.5 text-meta text-muted-foreground"
                    data-testid="materials-hint"
                  >
                    <Star className="size-3.5 fill-amber-500 text-amber-500 shrink-0" />
                    <span>
                      Senza audio la scaletta segue <b>{primaryMaterialName}</b>; gli altri
                      materiali sono contesto.
                    </span>
                  </div>
                )}
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
                    const isSelected = selectedSlot === h
                    return (
                      <button
                        key={`${h.materia}-${h.start_time}-${i}`}
                        type="button"
                        disabled={h.is_recorded}
                        onClick={() => handleSelectSlot(h)}
                        className={cn(
                          'flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-left text-meta transition-all min-w-0',
                          isSelected && 'border-primary ring-1 ring-primary bg-primary/10',
                          h.is_recorded && 'opacity-50 cursor-not-allowed',
                        )}
                        aria-label={h.is_recorded ? `${h.materia} - Già registrata` : `${h.materia} ${h.start_time}-${h.end_time}${h.docente ? ` - ${h.docente}` : ''}`}
                        data-testid={`calendar-slot-${i}`}
                      >
                        <span className="w-1 self-stretch rounded-full bg-primary" />
                        <div className="flex flex-col leading-tight">
                          <span className="font-semibold text-foreground text-xs">{h.materia}</span>
                          <span className="text-[11px] text-muted-foreground tabular-nums">
                            {h.start_time}–{h.end_time}
                          </span>
                        </div>
                        {h.is_recorded && (
                          <Check className="size-3.5 text-emerald-600 shrink-0 ml-1" />
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
                showSlots && 'hidden',
              )}
              data-testid="manual-fields"
            >
              <label className={labelText}>
                Materia
                <input
                  className={field}
                  list={`${listId}-materie`}
                  value={materia}
                  required
                  disabled={busy}
                  onChange={(e) => setMateria(e.target.value)}
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
                  className={field}
                  type="date"
                  value={date}
                  required
                  disabled={busy}
                  onChange={(e) => setDate(e.target.value)}
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
        {errorText && <Alert tone="danger">{errorText}</Alert>}
        {upload && <ProgressBar value={percent} label="Caricamento" className="my-3 h-1.5" />}
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
                  ) : (
                    `${item.code === 'duplicate_lesson' ? 'già presente' : 'rifiutata'} · ${item.reason}`
                  )}
                </li>
              ))}
            </ul>
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

          {kind !== 'zip' && (
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
                disabled={busy}
                onClick={() => setSolo(!solo)}
              />
              <IconButton
                label="Revisione"
                icon={ShieldCheck}
                aria-pressed={review}
                active={review && !solo}
                disabled={busy || solo}
                onClick={() => setReview(!review)}
              />
              <IconButton
                label="Arricchimento"
                icon={Image}
                aria-pressed={enrichment}
                active={enrichment && !solo}
                disabled={busy || solo}
                onClick={() => setEnrichment(!enrichment)}
              />
              <IconButton
                label="Allega documenti alle unità"
                icon={Paperclip}
                aria-pressed={attachMaterials}
                active={attachMaterials && materialFiles.length > 0 && !solo}
                disabled={busy || solo || materialFiles.length === 0}
                onClick={() => setAttachMaterials(!attachMaterials)}
                data-testid="attach-materials-btn"
              />
            </div>
          )}
        </div>
      </form>
    </Modal>
  )
}
