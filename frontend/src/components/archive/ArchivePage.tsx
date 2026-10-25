import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Crop,
  Eye,
  EyeOff,
  FileAudio,
  FileText,
  Grid2X2,
  Image,
  ImagePlus,
  Layers,
  Plus,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import {
  archiveFilesApi,
  compressPages,
  defaultExtraction,
  type ArchiveDetail,
  type SourceOptions,
} from '@/api/archive'
import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { MediaCropView } from '@/components/lesson/panels/MediaCropView'
import { UseOptions } from '@/components/sources/AddSourceDialog'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { SelectionBar } from '@/components/ui/selection-bar'
import { cn } from '@/lib/utils'
import { formatBytes } from '@/lib/jobs'
import { selectPage } from './selection'

const icons = { slide: Layers, testo: FileText, audio: FileAudio, immagine: Image }
const filters = [
  ['', 'Tutti', Archive],
  ['slide', 'Slide e PDF', Layers],
  ['testo', 'Testo', FileText],
  ['audio', 'Audio', FileAudio],
  ['immagine', 'Immagini', Image],
] as const
const color = (id: number | null) =>
  id === null ? '#cbd5e1' : ['#5d8dc5', '#b47d9e', '#70a695', '#b79b58', '#9386bb'][id % 5]
const imageUrl = (sha: string, n: number, version = 0) => `/api/v1/archive/${sha}/pages/${n}.png?v=${version}`

function ArchiveListSkeleton() {
  return (
    <div aria-busy="true" aria-label="Carico l'archivio" role="status" className="space-y-2">
      {[70, 50, 65, 45, 60, 55].map((w, i) => (
        <div key={i} className="flex min-h-14 items-center gap-3 rounded-lg p-3">
          <div className="rt-shimmer size-5 shrink-0 rounded" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="rt-shimmer h-4 rounded" style={{ width: `${w}%` }} />
            <div className="rt-shimmer h-3 w-1/3 rounded" />
          </div>
        </div>
      ))}
    </div>
  )
}

function ArchiveDetailSkeleton() {
  return (
    <div aria-busy="true" aria-label="Carico l'archivio" role="status" className="space-y-4">
      <div className="rt-shimmer h-64 w-full rounded-lg" />
      <div className="space-y-2">
        <div className="rt-shimmer h-4 w-3/4 rounded" />
        <div className="rt-shimmer h-3 w-1/2 rounded" />
      </div>
    </div>
  )
}

export function ArchivePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const origin = Number(params.get('da')) || null
  const lessons = useLessons()
  const [subject, setSubject] = useState<string | null>(null)
  const materia = subject ?? lessons.data?.find((l) => l.id === origin)?.materia ?? ''
  const isMateriaReady = !origin || subject !== null || Boolean(lessons.data)
  const [kind, setKind] = useState('')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(handle)
  }, [query])

  const [chosen, setChosen] = useState<string | null>(params.get('file'))
  const files = useQuery({
    queryKey: ['archive', 'list', materia, kind, debouncedQuery],
    queryFn: () =>
      archiveFilesApi.list({ materia: materia || undefined, tipo: kind || undefined, q: debouncedQuery || undefined }),
    enabled: isMateriaReady,
  })
  const subjects = [...new Set((lessons.data ?? []).map((l) => l.materia).filter(Boolean))].sort()
  const sha = chosen ?? files.data?.[0]?.impronta
  const root = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem('rt.archive.detailWidth'))
    return Number.isFinite(saved) && saved >= 380 ? saved : 560
  })
  useEffect(() => {
    const clamp = () =>
      setWidth((previous) =>
        Math.max(
          380,
          Math.min(previous, Math.max(380, (root.current?.clientWidth || window.innerWidth) - 300)),
        ),
      )
    clamp()
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [])
  const drag = useRef<{ x: number; width: number } | null>(null)
  const resize = (next: number) => {
    const max = Math.max(380, (root.current?.clientWidth || window.innerWidth) - 300)
    const value = Math.max(380, Math.min(max, next))
    setWidth(value)
    localStorage.setItem('rt.archive.detailWidth', String(value))
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background p-5" data-testid="archive-page">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <IconButton
          icon={ArrowLeft}
          label="Indietro"
          onClick={() => (origin ? navigate(`/lezioni/${origin}?panel=arricchimento`) : navigate(-1))}
        />
        <input
          aria-label="Cerca nell'archivio"
          placeholder="Cerca"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setChosen(null)
          }}
          className="min-w-32 flex-1 rounded-lg border bg-card px-3 py-2 text-body"
        />
        <select
          aria-label="Materia"
          value={materia}
          onChange={(e) => {
            setSubject(e.target.value)
            setChosen(null)
          }}
          className="rounded-lg border bg-card p-2 text-body"
        >
          <option value="">Tutte le materie</option>
          {subjects.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {filters.map(([value, label, icon]) => (
            <IconButton
              key={value}
              label={label}
              icon={icon}
              active={kind === value}
              onClick={() => {
                setKind(value)
                setChosen(null)
              }}
            />
          ))}
        </div>
      </header>
      {files.error && <Alert tone="danger">{errorMessage(files.error)}</Alert>}
      <div ref={root} className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="min-w-0 flex-1 overflow-auto pr-3 md:min-w-[300px]" aria-label="File dell'archivio">
          {files.isPending && <ArchiveListSkeleton />}
          {!files.isPending && files.data?.length === 0 && (
            <div className="flex flex-col items-center gap-2 p-12 text-muted-foreground">
              <Archive className="size-8" />
              <span>Nessun file</span>
            </div>
          )}
          {!files.isPending && files.data?.map((file) => {
            const Icon = icons[file.tipo as keyof typeof icons] ?? FileText
            return (
              <button
                key={file.impronta}
                type="button"
                aria-pressed={sha === file.impronta}
                onClick={() => setChosen(file.impronta)}
                className={cn(
                  'mb-1 flex w-full items-center gap-3 rounded-lg p-3 text-left transition-colors hover:bg-muted',
                  sha === file.impronta && 'bg-muted',
                )}
              >
                <Icon className="size-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <span className="block truncate text-body font-medium">{file.nome}</span>
                  <span className="text-meta text-muted-foreground">
                    {file.tipo === 'audio'
                      ? `${Math.round((file.durata_s ?? 0) / 60)} min`
                      : `${file.pagine_totali ?? 0} pagine`}{' '}
                    · {file.usi} lezioni
                  </span>
                </div>
                {file.da_continuare && (
                  <span className="rounded bg-background px-2 py-1 text-meta text-muted-foreground">
                    pag. {file.da_continuare}
                  </span>
                )}
              </button>
            )
          })}
        </div>
        {sha && (
          <>
            <div
              role="separator"
              aria-label="Larghezza del dettaglio"
              aria-orientation="vertical"
              aria-valuenow={width}
              aria-valuemin={380}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                  e.preventDefault()
                  resize(width + (e.key === 'ArrowLeft' ? 1 : -1) * (e.shiftKey ? 80 : 20))
                }
              }}
              onPointerDown={(e) => {
                drag.current = { x: e.clientX, width }
                e.currentTarget.setPointerCapture(e.pointerId)
              }}
              onPointerMove={(e) => {
                if (drag.current) resize(drag.current.width + drag.current.x - e.clientX)
              }}
              onPointerUp={(e) => {
                drag.current = null
                e.currentTarget.releasePointerCapture(e.pointerId)
              }}
              onPointerCancel={() => {
                drag.current = null
              }}
              className="mx-1 hidden w-2 shrink-0 cursor-col-resize rounded hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring md:block"
            />
            <aside
              style={{ width, maxWidth: '100%' }}
              className="min-w-0 shrink-0 rounded-xl border bg-card p-4"
            >
              <ArchiveDetailPanel
                key={sha}
                sha={sha}
                origin={origin}
                initialPage={params.get('file') === sha ? Number(params.get('pagina')) || null : null}
                initialCrop={params.get('file') === sha && params.get('ritaglia') === '1'}
                onDeleted={() => setChosen(null)}
              />
            </aside>
          </>
        )}
      </div>
    </div>
  )
}

function ArchiveDetailPanel({
  sha,
  origin,
  initialPage,
  initialCrop,
  onDeleted,
}: {
  sha: string
  origin: number | null
  initialPage: number | null
  initialCrop: boolean
  onDeleted: () => void
}) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['archive', 'detail', sha], queryFn: () => archiveFilesApi.detail(sha) })
  const detail = query.data
  const [selected, setSelected] = useState<number[]>([])
  const anchor = useRef<number | null>(null)
  const [single, setSingle] = useState(initialPage !== null)
  const [pageNumber, setPageNumber] = useState(initialPage ?? 1)
  const [cropping, setCropping] = useState(initialCrop)
  const [add, setAdd] = useState<'source' | 'media' | null>(null)
  const [confirm, setConfirm] = useState<'file' | 'pages' | null>(null)
  const [pending, setPending] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const numbers = useMemo(() => detail?.pagine.map((p) => p.numero) ?? [], [detail])
  const current = numbers.includes(pageNumber) ? pageNumber : numbers[0]
  const chosen = single && current ? [current] : selected
  const move = (delta: number) => {
    const index = numbers.indexOf(current)
    setPageNumber(numbers[Math.max(0, Math.min(numbers.length - 1, index + delta))] ?? 1)
  }
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, select, [contenteditable=true]') || cropping)
        return
      if (e.key === 'Escape') setSelected([])
      if (
        single &&
        (e.key === 'ArrowLeft' || e.key === 'ArrowRight') &&
        !(e.target as HTMLElement).closest('[role=separator]')
      ) {
        e.preventDefault()
        const index = numbers.indexOf(current)
        setPageNumber(
          numbers[Math.max(0, Math.min(numbers.length - 1, index + (e.key === 'ArrowRight' ? 1 : -1)))] ?? 1,
        )
      }
    }
    document.addEventListener('keydown', listener)
    return () => document.removeEventListener('keydown', listener)
  }, [numbers, current, single, cropping])
  async function act(action: () => Promise<unknown>, after?: () => void) {
    setPending(true)
    setProblem(null)
    try {
      await action()
      after?.()
      await client.invalidateQueries({ queryKey: ['archive'] })
      await client.invalidateQueries({ queryKey: ['lessons'] })
    } catch (error) {
      setProblem(errorMessage(error))
      throw error
    } finally {
      setPending(false)
    }
  }
  const run = (action: () => Promise<unknown>, after?: () => void) => {
    void act(action, after).catch(() => {})
  }
  if (query.error) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  if (query.isPending || !detail) return <ArchiveDetailSkeleton />
  const allIgnored = chosen.every((n) => detail.pagine.find((p) => p.numero === n)?.ignorata)
  const crop = () => {
    if (chosen.length === 1) {
      setSingle(true)
      setPageNumber(chosen[0])
      setCropping(true)
    }
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold">{detail.nome}</h1>
          <span className="text-meta text-muted-foreground">
            {detail.tipo === 'audio'
              ? `${Math.round((detail.durata_s ?? 0) / 60)} min`
              : `${detail.pagine_totali ?? 0} pagine`}{' '}
            · {formatBytes(detail.dimensione)}
          </span>
        </div>
        <IconButton
          icon={Plus}
          label="Aggiungi alla lezione come fonte"
          active={add === 'source'}
          onClick={() => setAdd(add === 'source' ? null : 'source')}
        />
        <IconButton
          icon={Trash2}
          label="Elimina file"
          unavailable={detail.usi ? `Usato da ${detail.usi} lezioni` : undefined}
          onClick={() => setConfirm('file')}
        />
      </div>
      {problem && <Alert tone="danger">{problem}</Alert>}
      {add && (
        <AddPanel
          key={add}
          detail={detail}
          selected={chosen}
          origin={origin}
          mode={add}
          pending={pending}
          onClose={() => setAdd(null)}
          onAdd={(lessonId, pages, uso) =>
            act(
              () =>
                add === 'media'
                  ? archiveFilesApi.addToMedia(sha, lessonId, pages ?? [])
                  : archiveFilesApi.addToLesson(sha, lessonId, pages, uso, defaultExtraction(detail.nome)),
              () => setAdd(null),
            )
          }
        />
      )}
      {numbers.length > 0 && (
        <>
          <div className="flex items-center gap-1">
            <IconButton icon={Grid2X2} label="Griglia" active={!single} onClick={() => setSingle(false)} />
            <IconButton
              icon={FileText}
              label="Una pagina alla volta"
              active={single}
              onClick={() => {
                setSingle(true)
                setPageNumber(selected[0] ?? current)
              }}
            />
            {single && (
              <div className="ml-auto flex items-center gap-1">
                <IconButton
                  icon={ChevronLeft}
                  label="Pagina precedente (←)"
                  disabled={numbers.indexOf(current) === 0}
                  onClick={() => move(-1)}
                />
                <span className="text-meta tabular-nums">
                  {current} / {detail.pagine_totali}
                </span>
                <IconButton
                  icon={ChevronRight}
                  label="Pagina successiva (→)"
                  disabled={numbers.indexOf(current) === numbers.length - 1}
                  onClick={() => move(1)}
                />
              </div>
            )}
          </div>
          {cropping && current ? (
            <MediaCropView
              image={{
                alt_text: detail.nome,
                slide_title: '',
                name: detail.nome,
                url: imageUrl(sha, current, query.dataUpdatedAt),
                source: `archive:${sha}:${current}`,
                source_name: detail.nome,
                page: current,
                in_assets: false,
                units: [],
                in_document: false,
                macro_ids: [],
                descritta: true,
              }}
              onClose={() => setCropping(false)}
              isPending={pending}
              onSave={(rect, replace) =>
                run(
                  () => archiveFilesApi.crop(sha, current, rect, replace),
                  () => setCropping(false),
                )
              }
            />
          ) : single ? (
            <div className="flex max-h-[400px] justify-center overflow-auto rounded-lg bg-muted/30">
              <img
                className="max-h-[390px] max-w-full object-contain"
                src={imageUrl(sha, current, query.dataUpdatedAt)}
                alt={`Pagina ${current}`}
              />
            </div>
          ) : (
            <div
              className="grid max-h-[440px] grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-3 overflow-auto p-1"
              aria-label="Pagine"
            >
              {detail.pagine.map((p) => (
                <button
                  key={p.numero}
                  type="button"
                  aria-label={`Pagina ${p.numero}`}
                  aria-pressed={selected.includes(p.numero)}
                  onClick={(e) => {
                    setSelected(
                      selectPage(
                        selected,
                        p.numero,
                        numbers,
                        anchor.current,
                        e.shiftKey,
                        e.metaKey || e.ctrlKey,
                      ),
                    )
                    anchor.current = p.numero
                  }}
                  className={cn(
                    'relative rounded-lg border p-1 text-left outline-offset-2',
                    selected.includes(p.numero) && 'outline-2 outline-link',
                    p.ignorata && 'border-dashed opacity-45',
                  )}
                >
                  <img
                    loading="lazy"
                    className="aspect-[3/4] w-full rounded object-contain"
                    src={imageUrl(sha, p.numero, query.dataUpdatedAt)}
                    alt=""
                  />
                  <div className="mt-1 flex items-center justify-between px-1 text-xs text-muted-foreground">
                    <span>{p.numero}</span>
                    {p.ignorata && <EyeOff className="size-3" />}
                  </div>
                  <div className="mt-1 h-1 rounded-full" style={{ background: color(p.lezione_id) }} />
                </button>
              ))}
            </div>
          )}
          {!cropping && chosen.length > 0 && (
            <div className="flex justify-center">
              <SelectionBar
                count={
                  single ? `pag. ${current}` : `${chosen.length} ${chosen.length === 1 ? 'pagina' : 'pagine'}`
                }
              >
                <IconButton
                  icon={ImagePlus}
                  label="Aggiungi ai media di una lezione"
                  className="text-blue-600"
                  active={add === 'media'}
                  onClick={() => setAdd(add === 'media' ? null : 'media')}
                />
                <IconButton
                  icon={allIgnored ? Eye : EyeOff}
                  label={allIgnored ? 'Non ignorare' : 'Ignora'}
                  disabled={pending}
                  onClick={() => run(() => archiveFilesApi.ignore(sha, chosen, !allIgnored))}
                />
                <IconButton
                  icon={Crop}
                  label="Ritaglia"
                  unavailable={chosen.length !== 1 ? 'Una pagina alla volta' : undefined}
                  onClick={crop}
                />
                <IconButton
                  icon={Trash2}
                  label="Elimina per sempre"
                  className="text-danger"
                  disabled={pending}
                  onClick={() => setConfirm('pages')}
                />
              </SelectionBar>
            </div>
          )}
        </>
      )}
      {detail.trascrizione_inizio && (
        <p className="max-h-40 overflow-auto whitespace-pre-line text-body text-muted-foreground">
          {detail.trascrizione_inizio}
        </p>
      )}
      <div className="flex flex-col gap-2">
        {detail.lezioni.map((l, index) => (
          <div key={l.id ?? index} className="flex items-center gap-2 text-meta">
            <span className="size-2 rounded-full" style={{ background: color(l.id) }} />
            {l.id ? (
              <Link to={`/lezioni/${l.id}`} className="truncate hover:underline">
                {l.titolo}
              </Link>
            ) : (
              <span>{l.titolo}</span>
            )}
            <span className="ml-auto text-muted-foreground">
              {l.data}
              {l.pagine && ` · ${compressPages(l.pagine)}`}
            </span>
          </div>
        ))}
      </div>
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'file' ? 'Eliminare il file?' : 'Eliminare le pagine per sempre?'}
        confirmLabel="Elimina"
        confirmDisabled={pending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          run(
            () =>
              confirm === 'file' ? archiveFilesApi.delete(sha) : archiveFilesApi.deletePages(sha, chosen),
            () => {
              if (confirm === 'file') onDeleted()
              setConfirm(null)
              setSelected([])
            },
          )
        }
      >
        <></>
      </ConfirmDialog>
    </div>
  )
}

function AddPanel({
  detail,
  selected,
  origin,
  mode,
  pending,
  onClose,
  onAdd,
}: {
  detail: ArchiveDetail
  selected: number[]
  origin: number | null
  mode: 'source' | 'media'
  pending: boolean
  onClose: () => void
  onAdd: (lessonId: number, pages: number[] | null, uso: NonNullable<SourceOptions['uso']>) => Promise<void>
}) {
  const lessons = useLessons()
  const eligible = [...(lessons.data ?? [])]
    .filter((l) => l.id === origin || detail.materie.length === 0 || detail.materie.includes(l.materia))
    .sort((a, b) => b.data.localeCompare(a.data))
  const [lessonId, setLessonId] = useState(origin ?? 0)
  const target = lessonId || eligible[0]?.id || 0
  const range = detail.da_continuare?.split('–')
  const [from, setFrom] = useState(range?.[0] ?? '1')
  const [to, setTo] = useState(range?.[1] ?? String(detail.pagine_totali ?? ''))
  const [uso, setUso] = useState<NonNullable<SourceOptions['uso']>>('contesto')
  const [problem, setProblem] = useState<string | null>(null)
  async function submit() {
    try {
      const start = Number(from),
        end = Number(to)
      if (
        mode === 'source' &&
        selected.length === 0 &&
        detail.tipo !== 'audio' &&
        detail.pagine_totali !== null &&
        (!Number.isInteger(start) ||
          !Number.isInteger(end) ||
          start < 1 ||
          end < start ||
          end > (detail.pagine_totali ?? 0))
      )
        throw new Error('Pagine fuori intervallo')
      const pages = selected.length
        ? selected
        : detail.tipo === 'audio' || detail.pagine_totali === null
          ? null
          : Array.from({ length: end - start + 1 }, (_, i) => start + i)
      await onAdd(target, pages, uso)
    } catch (error) {
      setProblem(errorMessage(error))
    }
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3" aria-label="Aggiungi">
      <select
        aria-label="Lezione"
        value={target}
        onChange={(e) => setLessonId(Number(e.target.value))}
        className="rounded border bg-card p-2 text-body"
      >
        {eligible.map((l) => (
          <option key={l.id} value={l.id}>
            {l.data} · {l.titolo || l.argomenti || l.materia}
          </option>
        ))}
      </select>
      {mode === 'source' &&
        detail.tipo !== 'audio' &&
        detail.pagine_totali !== null &&
        (selected.length > 0 ? (
          <span className="text-meta">Pagine: {compressPages(selected)}</span>
        ) : (
          <div className="flex gap-3">
            <label>
              Da
              <input
                aria-label="Da"
                type="number"
                min="1"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="ml-1 w-20 rounded border bg-card p-1"
              />
            </label>
            <label>
              A
              <input
                aria-label="A"
                type="number"
                min={from}
                max={detail.pagine_totali ?? undefined}
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="ml-1 w-20 rounded border bg-card p-1"
              />
            </label>
          </div>
        ))}
      {mode === 'source' && <UseOptions value={uso} onChange={setUso} />}
      {problem && <Alert tone="danger">{problem}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Annulla
        </Button>
        <Button onClick={submit} disabled={pending || !target}>
          Aggiungi
        </Button>
      </div>
    </div>
  )
}
