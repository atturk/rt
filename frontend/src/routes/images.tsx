import { Images } from 'lucide-react'
import { useCallback, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useLesson, useLessonDocument } from '@/api/hooks'
import { useAddImages, useLessonImages, useRefreshImages } from '@/api/images'
import { useOutline } from '@/api/jobs'
import { CountInput } from '@/components/CountInput'
import { JobProgress } from '@/components/JobProgress'
import { LessonPicker } from '@/components/LessonPicker'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { lessonTitle } from '@/lib/format'
import { PER_UNIT_MAX, PER_UNIT_MIN, parseCount } from '@/lib/count'
import { withImageUrls } from '@/lib/images'
import type { Area } from './types'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.gif,application/pdf,image/*'

function ImagesIndex() {
  return (
    <LessonPicker
      title="Immagini"
      intro="Scegli una lezione per aggiungere slide in PDF, foto della lavagna o immagini dal web al documento finale."
      href={(l) => `/lezioni/${l.id}/immagini`}
      ready={(l) => l.phases.build === 'VALID'}
      notReady="serve prima il documento finale"
    />
  )
}

type Outline = Schemas['Outline']

/** Scelta delle unità per la ricerca web: tutte, oppure caselle raggruppate per sezione. */
function UnitPicker({
  outline,
  selected,
  onChange,
}: {
  outline: Outline
  selected: Set<string>
  onChange: (next: Set<string>) => void
}) {
  function toggle(ids: string[], on: boolean) {
    const next = new Set(selected)
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)))
    onChange(next)
  }
  return (
    <div className="flex max-h-80 flex-col gap-3 overflow-y-auto rounded-md border p-3" data-testid="unit-picker">
      {outline.macro_sections.map((macro) => {
        const ids = macro.units.map((u) => u.id)
        const count = ids.filter((id) => selected.has(id)).length
        return (
          <fieldset key={macro.id} className="flex flex-col gap-1" data-testid="unit-section" data-section-id={macro.id}>
            <legend className="w-full">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={count === ids.length && ids.length > 0}
                  ref={(el) => {
                    if (el) el.indeterminate = count > 0 && count < ids.length
                  }}
                  onChange={(e) => toggle(ids, e.target.checked)}
                  aria-label={`Seleziona sezione ${macro.id}. ${macro.title}`}
                />
                <span>
                  {macro.id}. {macro.title}
                </span>
                <span className="ml-auto text-xs font-normal text-muted-foreground">seleziona sezione</span>
              </label>
            </legend>
            <ul className="flex flex-col gap-1 pl-6">
              {macro.units.map((unit) => (
                <li key={unit.id}>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={selected.has(unit.id)}
                      onChange={(e) => toggle([unit.id], e.target.checked)}
                      data-unit-id={unit.id}
                    />
                    <span>
                      <span className="tabular-nums text-muted-foreground">{unit.id}</span> {unit.title}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
        )
      })}
    </div>
  )
}

function SearxngError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === 'searxng_not_configured') {
    return (
      <Alert tone="danger">
        {error.message}{' '}
        <Link to="/impostazioni" className="font-medium underline underline-offset-2">
          Apri le Impostazioni
        </Link>
      </Alert>
    )
  }
  return <Alert tone="danger">{errorMessage(error)}</Alert>
}

function UploadForm({ lessonId, onStarted }: { lessonId: number; onStarted: (jobId: string) => void }) {
  const add = useAddImages(lessonId)
  const outline = useOutline(lessonId)
  const [files, setFiles] = useState<File[]>([])
  const [perUnit, setPerUnit] = useState('0')
  const [scope, setScope] = useState<'all' | 'some'>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [formError, setFormError] = useState<string | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const parsed = parseCount(perUnit)
  const searching = parsed.ok && parsed.value > 0

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!parsed.ok) {
      setFormError(parsed.error)
      return
    }
    if (parsed.value > 0 && scope === 'some' && selected.size === 0) {
      setFormError("Scegli almeno un'unità, oppure cerca per tutte le unità.")
      return
    }
    if (files.length === 0 && parsed.value === 0) {
      setFormError('Carica un file o scegli quante immagini cercare sul web.')
      return
    }
    setFormError(null)
    const order = outline.data?.macro_sections.flatMap((m) => m.units.map((u) => u.id)) ?? []
    add.mutate(
      { files, perUnit: parsed.value, units: scope === 'some' ? order.filter((id) => selected.has(id)) : null },
      {
        onSuccess: (accepted) => {
          setFiles([])
          setInputKey((k) => k + 1)
          onStarted(accepted.job_id)
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
      <div className="flex flex-col gap-1">
        <Label htmlFor="image-files">PDF o foto</Label>
        <Input
          key={inputKey}
          id="image-files"
          type="file"
          multiple
          accept={ACCEPT}
          className="h-auto py-1.5"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <p className="text-xs text-muted-foreground">
          Un PDF di slide viene diviso in pagine; più foto vengono analizzate insieme. Ogni immagine riceve una descrizione e finisce
          nella sezione giusta del documento.
        </p>
      </div>
      <div className="flex flex-col gap-1 sm:max-w-xs">
        <Label htmlFor="web-search">Immagini per unità</Label>
        <CountInput
          id="web-search"
          value={perUnit}
          onChange={(v) => {
            setPerUnit(v)
            setFormError(null)
          }}
          invalid={!parsed.ok}
          aria-describedby="web-search-help"
        />
        <p id="web-search-help" className="text-xs text-muted-foreground">
          Immagini da cercare sul web per ogni unità, da {PER_UNIT_MIN} a {PER_UNIT_MAX}; 0 = nessuna ricerca.
        </p>
      </div>
      {searching && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium">Unità in cui cercare</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="unit-scope" checked={scope === 'all'} onChange={() => setScope('all')} />
              Tutte le unità
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="unit-scope" checked={scope === 'some'} onChange={() => setScope('some')} />
              Scegli le unità
            </label>
          </div>
          {scope === 'some' &&
            (outline.isError ? (
              <Alert tone="danger">{errorMessage(outline.error)}</Alert>
            ) : outline.data ? (
              <>
                <UnitPicker outline={outline.data} selected={selected} onChange={setSelected} />
                <p className="text-xs text-muted-foreground" aria-live="polite">
                  Unità scelte: {selected.size}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Carico le unità…</p>
            ))}
        </fieldset>
      )}
      {formError && <Alert tone="danger">{formError}</Alert>}
      {add.isError && <SearxngError error={add.error} />}
      <Button type="submit" className="self-start" disabled={add.isPending}>
        Aggiungi le immagini
      </Button>
    </form>
  )
}

function Gallery({ lessonId }: { lessonId: number }) {
  const images = useLessonImages(lessonId)
  if (images.isError) return <Alert tone="danger">{errorMessage(images.error)}</Alert>
  const list = images.data?.images ?? []
  if (images.isSuccess && list.length === 0) return <p className="text-sm text-muted-foreground">Nessuna immagine ancora.</p>
  return (
    <ul className="grid grid-cols-2 gap-3 md:grid-cols-3" aria-label="Immagini della lezione">
      {list.map((img) => (
        <li key={img.name} data-testid="lesson-image" data-name={img.name} data-in-document={img.in_document}>
          <Card className="flex h-full flex-col gap-2 overflow-hidden">
            <img src={img.url} alt={img.alt_text || img.slide_title || img.name} loading="lazy" className="aspect-video w-full bg-muted object-contain" />
            <div className="flex flex-col gap-1 px-3 pb-3">
              <span className="line-clamp-2 text-xs font-medium">{img.slide_title || img.alt_text || img.name}</span>
              <span className="truncate text-[11px] text-muted-foreground" title={img.source}>
                {img.source}
              </span>
              <Badge tone={img.in_document ? 'success' : 'neutral'} className="self-start">
                {img.in_document ? 'Nel documento' : 'Non usata'}
              </Badge>
            </div>
          </Card>
        </li>
      ))}
    </ul>
  )
}

/** Anteprima del documento finale con le immagini servite dall'API. */
function DocumentPreview({ lessonId }: { lessonId: number }) {
  const doc = useLessonDocument(lessonId)
  if (doc.isPending) return <p className="text-sm text-muted-foreground">Carico il documento…</p>
  if (doc.isError) return <Alert tone="danger">{errorMessage(doc.error)}</Alert>
  return (
    <div
      data-testid="document-preview"
      className="rt-document max-h-[70vh] overflow-y-auto rounded-lg border bg-card p-5"
      // HTML già sanificato dall'API (markdown-it con html=False)
      dangerouslySetInnerHTML={{ __html: withImageUrls(doc.data.html, lessonId) }}
    />
  )
}

export function ImagesPage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  const [params, setParams] = useSearchParams()
  const jobId = params.get('job')
  const refresh = useRefreshImages(id)
  const onFinished = useCallback(() => void refresh(), [refresh])

  if (lesson.isPending) return <p className="text-sm text-muted-foreground">Carico la lezione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  const ready = lesson.data.phases.build === 'VALID'
  return (
    <section className="flex flex-col gap-4">
      <Link to="/immagini" className="text-xs text-muted-foreground hover:underline">
        ← Immagini: tutte le lezioni
      </Link>
      <h1 className="text-xl font-bold tracking-tight">Immagini · {lessonTitle(lesson.data)}</h1>
      {!ready && <Alert tone="warning">Le immagini si aggiungono al documento finale: completa prima la pipeline fino al build.</Alert>}
      {ready && (
        <Card className="flex flex-col gap-4 p-5">
          <h2 className="text-base font-bold">Aggiungi immagini</h2>
          <UploadForm lessonId={id} onStarted={(job) => setParams({ job })} />
          {jobId && <JobProgress jobId={jobId} label="Integrazione delle immagini" onFinished={onFinished} />}
        </Card>
      )}
      <Card className="flex flex-col gap-3 p-5">
        <h2 className="text-base font-bold">Immagini della lezione</h2>
        <Gallery lessonId={id} />
      </Card>
      {ready && (
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-base font-bold">Anteprima nel documento</h2>
          <DocumentPreview lessonId={id} />
        </Card>
      )}
    </section>
  )
}

export const imagesArea: Area = {
  routes: [
    { path: 'immagini', element: <ImagesIndex /> },
    { path: 'lezioni/:lessonId/immagini', element: <ImagesPage /> },
  ],
  nav: [{ to: '/immagini', label: 'Immagini', icon: Images }],
}
