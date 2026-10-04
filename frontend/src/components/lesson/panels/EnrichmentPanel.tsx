import { Image as ImageIcon, Search, Sparkles, Upload, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import { errorMessage, type Schemas } from '@/api/client'
import { useEnrichment, useEnrichmentActions } from '@/api/enrichment'
import { useAddImages, useLessonImages, useRefreshImages, type LessonImage } from '@/api/images'
import { useOutline } from '@/api/jobs'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { kindLabel } from '@/lib/enrichment'
import { parseCount, PER_UNIT_MAX, PER_UNIT_MIN } from '@/lib/count'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.gif,application/pdf,image/*'

function scrollToUnit(unitId?: string | null) {
  if (!unitId) return
  const el = document.getElementById(`unit-${unitId}`) || document.querySelector(`[data-unit-id="${unitId}"]`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export function EnrichmentPanel({ lessonId }: { lessonId?: number }) {
  const params = useParams()
  const id = lessonId ?? Number(params.lessonId)

  const images = useLessonImages(id)
  const refreshImages = useRefreshImages(id)
  const addImages = useAddImages(id)
  const outline = useOutline(id)

  const enrichment = useEnrichment(id)
  const { analyze, generate, action, refresh: refreshEnrichment } = useEnrichmentActions(id)

  const [openUpload, setOpenUpload] = useState(false)
  const [openSearch, setOpenSearch] = useState(false)
  const [uploadFiles, setUploadFiles] = useState<File[]>([])
  const [searchCount, setSearchCount] = useState('1')
  const [searchScope, setSearchScope] = useState<'all' | 'some'>('all')
  const [selectedUnits, setSelectedUnits] = useState<Set<string>>(new Set())
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [showIgnored, setShowIgnored] = useState(false)

  if (!Number.isFinite(id)) return null

  const imageList = images.data?.images ?? []
  const elements = enrichment.data?.elements ?? []
  const completedElements = elements.filter(
    (e) => e.status === 'ready',
  )
  const totalMedia = imageList.length + completedElements.length

  const visibleIdeas = elements.filter(
    (e) => e.status !== 'suppressed' && (showIgnored ? true : e.status !== 'dismissed'),
  )
  const ignoredCount = elements.filter((e) => e.status === 'dismissed').length

  const handleUploadSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!uploadFiles.length) return
    addImages.mutate(
      { files: uploadFiles, perUnit: 0, units: null },
      {
        onSuccess: (res) => {
          setUploadFiles([])
          setOpenUpload(false)
          if (res?.job_id) setActiveJobId(res.job_id)
        },
      },
    )
  }

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault()
    const parsed = parseCount(searchCount)
    if (!parsed.ok || parsed.value <= 0) return
    const order = outline.data?.macro_sections.flatMap((m) => m.units.map((u) => u.id)) ?? []
    addImages.mutate(
      {
        files: [],
        perUnit: parsed.value,
        units: searchScope === 'some' ? order.filter((uid) => selectedUnits.has(uid)) : null,
      },
      {
        onSuccess: (res) => {
          setOpenSearch(false)
          if (res?.job_id) setActiveJobId(res.job_id)
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-4 text-body" data-testid="enrichment-panel">
      {/* Sezione Media della lezione */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">
            Media della lezione · {totalMedia}
          </h3>
          <div className="flex items-center gap-1">
            <IconButton
              label="Aggiungi immagini (PDF o foto)"
              icon={Upload}
              className="size-7"
              active={openUpload}
              onClick={() => {
                setOpenUpload(!openUpload)
                setOpenSearch(false)
              }}
            />
            <IconButton
              label="Cerca immagini sul web"
              icon={Search}
              className="size-7"
              active={openSearch}
              onClick={() => {
                setOpenSearch(!openSearch)
                setOpenUpload(false)
              }}
            />
          </div>
        </div>

        {/* Scheda Aggiungi immagini */}
        {openUpload && (
          <Card className="flex flex-col gap-2.5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-body font-semibold">Aggiungi PDF o foto</span>
              <IconButton label="Chiudi" icon={X} className="size-6" onClick={() => setOpenUpload(false)} />
            </div>
            <form onSubmit={handleUploadSubmit} className="flex flex-col gap-2.5">
              <Input
                type="file"
                aria-label="PDF o foto"
                multiple
                accept={ACCEPT}
                className="h-auto py-1 text-meta"
                onChange={(e) => setUploadFiles(Array.from(e.target.files ?? []))}
              />
              <div className="flex justify-end gap-2 pt-1">
                <Button size="sm" variant="ghost" type="button" onClick={() => setOpenUpload(false)}>
                  Annulla
                </Button>
                <Button size="sm" variant="default" type="submit" disabled={!uploadFiles.length || addImages.isPending}>
                  Carica {uploadFiles.length > 0 ? `(${uploadFiles.length})` : ''}
                </Button>
              </div>
            </form>
          </Card>
        )}

        {/* Scheda Cerca sul web */}
        {openSearch && (
          <Card className="flex flex-col gap-2.5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-body font-semibold">Cerca immagini sul web</span>
              <IconButton label="Chiudi" icon={X} className="size-6" onClick={() => setOpenSearch(false)} />
            </div>
            <form onSubmit={handleSearchSubmit} className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2">
                <label htmlFor="search-per-unit" className="text-meta text-muted-foreground">
                  Immagini per unità ({PER_UNIT_MIN}–{PER_UNIT_MAX}):
                </label>
                <Input
                  id="search-per-unit"
                  type="number"
                  min={PER_UNIT_MIN}
                  max={PER_UNIT_MAX}
                  className="h-8 w-16 text-center text-meta"
                  value={searchCount}
                  onChange={(e) => setSearchCount(e.target.value)}
                />
              </div>

              <div className="flex items-center gap-3 text-meta">
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="scope"
                    checked={searchScope === 'all'}
                    onChange={() => setSearchScope('all')}
                  />
                  Tutte le unità
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="scope"
                    checked={searchScope === 'some'}
                    onChange={() => setSearchScope('some')}
                  />
                  Scegli unità
                </label>
              </div>

              {searchScope === 'some' && outline.data && (
                <fieldset className="max-h-36 overflow-y-auto rounded-md border p-2 text-meta">
                  <legend className="px-1 text-muted-foreground">Unità selezionate</legend>
                  {outline.data.macro_sections.flatMap((m) =>
                    m.units.map((u) => (
                      <label key={u.id} className="flex items-center gap-2 py-0.5">
                        <input
                          type="checkbox"
                          checked={selectedUnits.has(u.id)}
                          onChange={(e) => {
                            const next = new Set(selectedUnits)
                            if (e.target.checked) next.add(u.id)
                            else next.delete(u.id)
                            setSelectedUnits(next)
                          }}
                        />
                        <span className="truncate">
                          {u.id} {u.title}
                        </span>
                      </label>
                    )),
                  )}
                </fieldset>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <Button size="sm" variant="ghost" type="button" onClick={() => setOpenSearch(false)}>
                  Annulla
                </Button>
                <Button size="sm" variant="default" type="submit" disabled={addImages.isPending}>
                  Cerca
                </Button>
              </div>
            </form>
          </Card>
        )}

        {addImages.isError && <Alert tone="danger">{errorMessage(addImages.error)}</Alert>}
        {activeJobId && (
          <JobProgress
            jobId={activeJobId}
            label="Integrazione immagini"
            onFinished={() => {
              setActiveJobId(null)
              void refreshImages()
            }}
          />
        )}

        {/* Griglia della Galleria */}
        <div className="grid grid-cols-3 gap-2.5 pt-1" role="group" aria-label="Media della lezione">
          {imageList.map((img: LessonImage) => {
            const unitLabel =
              img.in_document && (img.macro_ids ?? []).length > 0
                ? (img.macro_ids ?? []).join(', ')
                : img.source === 'pdf'
                  ? 'da PDF'
                  : 'non assegnata'
            const targetUnit = img.macro_ids?.[0] ?? null

            return (
              <button
                key={img.name}
                type="button"
                className="group flex flex-col gap-1 text-left cursor-pointer"
                aria-label={`Immagine ${unitLabel}: vai nel testo`}
                onClick={() => scrollToUnit(targetUnit)}
              >
                <div className="flex h-20 w-full items-center justify-center overflow-hidden rounded-lg border bg-muted transition-colors group-hover:border-primary">
                  {img.url ? (
                    <img
                      src={img.url}
                      alt={img.alt_text || img.slide_title || img.name}
                      className="size-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <ImageIcon className="size-6 text-muted-foreground" aria-hidden />
                  )}
                </div>
                <span className="truncate text-meta text-muted-foreground group-hover:text-foreground">
                  Immagine · {unitLabel}
                </span>
              </button>
            )
          })}

          {completedElements.map((el) => {
            const kindText = kindLabel(el.kind)
            return (
              <button
                key={el.id}
                type="button"
                className="group flex flex-col gap-1 text-left cursor-pointer"
                aria-label={`${kindText} ${el.unit_id}: vai nel testo`}
                onClick={() => scrollToUnit(el.unit_id)}
              >
                <div className="flex h-20 w-full items-center justify-center overflow-hidden rounded-lg border bg-muted transition-colors group-hover:border-primary">
                  <Sparkles className="size-6 text-primary" aria-hidden />
                </div>
                <span className="truncate text-meta text-muted-foreground group-hover:text-foreground">
                  {kindText} · {el.unit_id}
                </span>
              </button>
            )
          })}
        </div>

        {totalMedia === 0 && (
          <p className="py-2 text-center text-meta text-muted-foreground">Nessun media presente nella lezione.</p>
        )}
      </div>

      <hr className="border-border" />

      {/* Sezione Idee per la lezione */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">
            Idee per la lezione
          </h3>
          <IconButton
            label="Analizza la lezione"
            icon={Sparkles}
            className="size-7"
            disabled={analyze.isPending}
            onClick={() => analyze.mutate()}
          />
        </div>

        {analyze.isError && <Alert tone="danger">{errorMessage(analyze.error)}</Alert>}
        {analyze.data && (
          <JobProgress jobId={analyze.data.job_id} label="Analisi delle idee" onFinished={refreshEnrichment} />
        )}

        <ul className="flex flex-col divide-y divide-border/60" aria-label="Elenco idee">
          {visibleIdeas.map((e: Schemas['Element']) => (
            <li key={e.id} className="flex flex-col gap-1.5 py-2.5">
              <p className="text-meta text-muted-foreground">
                {kindLabel(e.kind)} · unità {e.unit_id}
              </p>
              <p className="text-body font-medium">{e.title || e.description}</p>
              <div className="flex items-center gap-2 pt-0.5">
                <Button
                  size="sm"
                  variant="default"
                  disabled={generate.isPending}
                  onClick={() => generate.mutate({ element_id: e.id })}
                >
                  <Sparkles className="size-3" /> Genera
                </Button>
                {e.status === 'dismissed' ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={action.isPending}
                    onClick={() => action.mutate({ element: e.id, action: 'restore' })}
                  >
                    Ripristina
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={action.isPending}
                    onClick={() => action.mutate({ element: e.id, action: 'dismiss' })}
                  >
                    Ignora
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>

        {visibleIdeas.length === 0 && (
          <p className="text-meta text-muted-foreground">
            Nessuna idea.
          </p>
        )}

        {ignoredCount > 0 && (
          <button
            type="button"
            className="self-start text-meta text-link hover:underline"
            onClick={() => setShowIgnored(!showIgnored)}
          >
            {showIgnored ? 'Nascondi le idee ignorate' : `Mostra le ${ignoredCount} idee ignorate`}
          </button>
        )}
      </div>
    </div>
  )
}
