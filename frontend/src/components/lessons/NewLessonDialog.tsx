import { useQueryClient } from '@tanstack/react-query'
import { Archive, FileAudio, Play, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { invalidateAfterJob, useCreateLesson, useImportLessonZips, type ZipImportResult } from '@/api/jobs'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { JobProgress } from '@/components/JobProgress'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
import { AUDIO_EXTENSIONS, audioFileProblem, formatBytes } from '@/lib/jobs'
import { cn } from '@/lib/utils'

const DROP_TEXT = "Trascina l'audio o il pacchetto della lezione, o fai clic"

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const isZip = (file: File) => file.name.toLowerCase().endsWith('.zip')

/** audio (pipeline), zip (pacchetto esportato da RT, importato così com'è) o misto (errore). */
function uploadKind(files: File[]): 'audio' | 'zip' | 'misto' | null {
  if (files.length === 0) return null
  const zips = files.filter(isZip).length
  return zips === 0 ? 'audio' : zips === files.length ? 'zip' : 'misto'
}

const field = 'mt-1.5 block min-h-10 w-full rounded-md border bg-card p-2 text-body text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring'
const labelText = 'min-w-0 flex-1 text-meta text-muted-foreground'

/**
 * Popup Nuova lezione (schermate 00 e 00b): un solo riquadro per l'audio o per il pacchetto
 * .zip. Con l'audio: materia, docente, data e Avvia (importazione e pipeline, poi la pagina
 * della lezione); con lo .zip i campi spariscono e il pulsante diventa Importa
 * (POST /lessons/import-zip, nessuna pipeline).
 */
export function NewLessonDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const lessons = useLessons()
  const create = useCreateLesson()
  const zips = useImportLessonZips()
  const input = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [materia, setMateria] = useState('')
  const [docente, setDocente] = useState('')
  const [date, setDate] = useState(today)
  const [problem, setProblem] = useState<string | null>(null)
  const [zipJob, setZipJob] = useState<string | null>(null)
  const job = useJobStatus(zipJob)
  const result = job.data?.state === 'succeeded' ? (job.data.result as ZipImportResult | null) : null
  const kind = uploadKind(files)
  const busy = create.isPending || zips.isPending || (!!zipJob && !job.isError && !jobFinished(job.data))
  const subjects = [...new Set((lessons.data ?? []).map((l) => l.materia).filter(Boolean))].sort()
  const teachers = [...new Set((lessons.data ?? []).map((l) => l.docente?.trim()).filter(Boolean))].sort()

  const choose = (chosen: File[]) => {
    if (busy || chosen.length === 0) return
    setFiles(chosen)
    setProblem(null)
    setZipJob(null)
    create.reset()
    zips.reset()
  }

  const finished = useCallback(() => {
    invalidateAfterJob(client)
  }, [client])

  const imported = result?.results.filter((item) => item.status === 'imported' && item.lesson_id != null) ?? []
  const only = result && imported.length === 1 && result.rejected === 0 ? imported[0].lesson_id : null
  useEffect(() => {
    // Un solo pacchetto importato: si va dritti alla lezione.
    if (only == null) return
    onClose()
    navigate(`/lezioni/${only}`)
  }, [only, onClose, navigate])

  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    if (kind === 'zip') {
      zips.mutate(files, { onSuccess: (accepted) => setZipJob(accepted.job_id) })
      return
    }
    const issue = kind === 'misto'
      ? 'Scegli o solo audio o solo pacchetti .zip.'
      : audioFileProblem(files) ?? (materia.trim() ? null : 'Indica la materia.')
    setProblem(issue)
    if (issue) return
    create.mutate(
      { files, date, materia: materia.trim(), argomenti: '', docente: docente.trim(), run: true, mock: false, auto_accept: false, with_review: false },
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
  const errorText = error instanceof ApiError && error.code === 'payload_too_large'
    ? `${error.message} Dividi l'audio in più file più piccoli.`
    : error ? errorMessage(error) : null
  const total = files.reduce((sum, f) => sum + f.size, 0)

  return (
    <Modal open={open} onClose={onClose} title="Nuova lezione" testId="new-lesson">
      <form onSubmit={submit} aria-label="Nuova lezione" noValidate>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={['audio/*', '.zip', ...AUDIO_EXTENSIONS].join(',')}
          aria-label="Audio o pacchetto della lezione"
          onChange={(event) => {
            choose(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
        {files.length === 0 ? (
          <div
            role="button"
            tabIndex={0}
            aria-label={DROP_TEXT}
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
        ) : (
          <div
            className="my-4 flex min-h-[110px] items-center justify-center gap-2.5 rounded-lg border border-dashed px-4 py-3 text-foreground"
            data-testid="chosen-files"
            data-kind={kind}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault()
              choose(Array.from(event.dataTransfer.files))
            }}
          >
            {kind === 'zip' ? <Archive className="size-[18px] shrink-0" aria-hidden /> : <FileAudio className="size-[18px] shrink-0" aria-hidden />}
            <span className="min-w-0 text-meta [overflow-wrap:anywhere]">
              {files.length === 1 ? files[0].name : `${files.length} file · ${formatBytes(total)}`}
            </span>
            <IconButton label="Rimuovi" icon={X} disabled={busy} onClick={() => {
                setFiles([])
                setProblem(null)
                setZipJob(null)
              }} />
          </div>
        )}

        {kind !== 'zip' && (
          <>
            <div className="mb-3 flex gap-2 max-md:flex-wrap">
              <label className={labelText}>
                Materia
                <input className={field} list={`${listId}-materie`} value={materia} required disabled={busy} onChange={(e) => setMateria(e.target.value)} />
              </label>
              <label className={labelText}>
                Docente
                <input className={field} list={`${listId}-docenti`} value={docente} disabled={busy} onChange={(e) => setDocente(e.target.value)} />
              </label>
              <datalist id={`${listId}-materie`}>{subjects.map((s) => <option key={s} value={s} />)}</datalist>
              <datalist id={`${listId}-docenti`}>{teachers.map((t) => <option key={t} value={t} />)}</datalist>
            </div>
            <div className="mb-3 flex gap-2">
              <label className={labelText}>
                Data{date === today() && ' · oggi'}
                <input className={field} type="date" value={date} required disabled={busy} onChange={(e) => setDate(e.target.value)} />
              </label>
            </div>
          </>
        )}

        {problem && <Alert tone="danger">{problem}</Alert>}
        {errorText && <Alert tone="danger">{errorText}</Alert>}
        {upload && <ProgressBar value={percent} label="Caricamento" className="my-3 h-1.5" />}
        {zipJob && <div className="my-3"><JobProgress jobId={zipJob} label="Importazione del pacchetto" onFinished={finished} /></div>}
        {result && (imported.length !== 1 || result.rejected > 0) && (
          <ul className="my-3 text-meta" aria-label="Esito dell'importazione">
            {result.results.map((item, index) => (
              <li key={index}>
                {item.file}:{' '}
                {item.status === 'imported' ? (
                  <>importata{item.lesson_id != null && <> · <Link className="underline" to={`/lezioni/${item.lesson_id}`} onClick={onClose}>apri</Link></>}</>
                ) : (
                  `rifiutata · ${item.reason}`
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-1.5 flex justify-end">
          <Button type="submit" className="h-10 px-4 font-semibold" disabled={busy}>
            {kind === 'zip' ? <Upload aria-hidden /> : <Play aria-hidden />}
            {kind === 'zip' ? 'Importa' : 'Avvia'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
