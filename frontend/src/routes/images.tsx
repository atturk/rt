import { Images } from 'lucide-react'
import { useCallback, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLesson } from '@/api/hooks'
import { useAddImages, useLessonDocument, useLessonImages, useRefreshImages, withImageUrls } from '@/api/images'
import { JobProgress } from '@/components/JobProgress'
import { LessonPicker } from '@/components/LessonPicker'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { lessonTitle } from '@/lib/format'
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

function UploadForm({ lessonId, onStarted }: { lessonId: number; onStarted: (jobId: string) => void }) {
  const add = useAddImages(lessonId)
  const [files, setFiles] = useState<File[]>([])
  const [webSearch, setWebSearch] = useState(0)
  const [carousel, setCarousel] = useState(false)
  const [inputKey, setInputKey] = useState(0)

  function submit(e: FormEvent) {
    e.preventDefault()
    add.mutate(
      { files, webSearch, carousel },
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
    <form onSubmit={submit} className="flex flex-col gap-3">
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
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="web-search">Immagini da cercare sul web</Label>
          <Input
            id="web-search"
            type="number"
            min={0}
            max={20}
            value={webSearch}
            onChange={(e) => setWebSearch(Math.max(0, Math.min(20, Number(e.target.value) || 0)))}
          />
          <p className="text-xs text-muted-foreground">0 = nessuna ricerca. Serve SearXNG configurato.</p>
        </div>
        <label className="flex items-center gap-2 self-center text-sm">
          <input type="checkbox" checked={carousel} onChange={(e) => setCarousel(e.target.checked)} />
          Mostra le immagini come carosello (Obsidian)
        </label>
      </div>
      {add.isError && <Alert tone="danger">{errorMessage(add.error)}</Alert>}
      <Button type="submit" className="self-start" disabled={add.isPending || (files.length === 0 && webSearch === 0)}>
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
      className="prose-rt max-h-[70vh] overflow-y-auto rounded-lg border bg-card p-5 text-sm leading-relaxed [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-bold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-bold [&_h3]:mb-1 [&_h3]:mt-4 [&_h3]:font-semibold [&_img]:my-3 [&_img]:max-h-80 [&_img]:rounded-md [&_img]:border [&_p]:mb-2"
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
