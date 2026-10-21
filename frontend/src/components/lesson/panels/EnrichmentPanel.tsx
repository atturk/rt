import { Archive, CircleDot, FileText, Image, Layers, LayoutGrid, Rows3, ScanEye, Search, Sparkles, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router'

import { useArchiveSummary } from '@/api/archive'
import { errorMessage, type Schemas } from '@/api/client'
import { useEnrichment, useEnrichmentActions } from '@/api/enrichment'
import { useLesson, useLessonDocument } from '@/api/hooks'
import {
  copyMaterialPage,
  describeMedia,
  materialSourceId,
  deleteMedia,
  removeFromText,
  useAddImages,
  useLessonImages,
  useRefreshImages,
  type LessonImage,
} from '@/api/images'
import { useOutline } from '@/api/jobs'
import { useSources } from '@/api/sources'
import { formatBytes } from '@/lib/jobs'
import { JobProgress } from '@/components/JobProgress'
import {
  ENRICHMENT_MEDIA_DRAG_EVENT,
  ENRICHMENT_MEDIA_DROP_EVENT,
} from '@/components/shell/globalFileDropUtils'
import { Alert } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Tooltip } from '@/components/ui/tooltip'
import { assetUrl, kindLabel } from '@/lib/enrichment'
import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'
import { cn } from '@/lib/utils'
import { MediaGallery } from './MediaGallery'
import { MediaSelectionBar } from './MediaSelectionBar'
import { parseCount, PER_UNIT_MAX, PER_UNIT_MIN } from '@/lib/count'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.gif,application/pdf,image/*'

function findUnitForImage(imageName: string, markdown?: string): string | null {
  if (!markdown || !imageName) return null
  const clean = imageName.split('#')[0]
  const idx = markdown.indexOf(clean)
  if (idx === -1) return null
  const before = markdown.slice(0, idx)
  const matches = [...before.matchAll(/^###\s+(\S+)/gm)]
  if (matches.length > 0) {
    return matches[matches.length - 1][1]
  }
  return null
}

/** Porta l'editor sull'immagine (riferimento nel Markdown) o, se manca, sull'unità. */
function scrollToMedia(target: { imageName?: string | null; unitId?: string | null }) {
  window.dispatchEvent(new CustomEvent(EDITOR_SCROLL_EVENT, { detail: target }))
}

export function EnrichmentPanel({ lessonId }: { lessonId?: number }) {
  const params = useParams()
  const id = lessonId ?? Number(params.lessonId)

  const images = useLessonImages(id)
  const refreshImages = useRefreshImages(id)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const addImages = useAddImages(id)
  const outline = useOutline(id)
  const docQuery = useLessonDocument(id)

  const enrichment = useEnrichment(id)
  const { analyze, generate, action, refresh: refreshEnrichment } = useEnrichmentActions(id)

  const [openUpload, setOpenUpload] = useState(false)
  const [openSearch, setOpenSearch] = useState(false)
  const [uploadFiles, setUploadFiles] = useState<File[]>([])
  const [draggingUpload, setDraggingUpload] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [searchCount, setSearchCount] = useState('1')
  const [searchScope, setSearchScope] = useState<'all' | 'some'>('all')
  const [selectedUnits, setSelectedUnits] = useState<Set<string>>(new Set())
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [showIgnored, setShowIgnored] = useState(false)
  const [mediaDragActive, setMediaDragActive] = useState(false)
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set())
  const [canInsertAtCursor, setCanInsertAtCursor] = useState(false)
  const navigate = useNavigate()
  const lessonQuery = useLesson(id)
  const sourcesQuery = useSources(id)
  const archiveSummary = useArchiveSummary(lessonQuery.data?.materia)
  const [mediaFilter, setMediaFilter] = useState<'all' | 'undescribed'>('all')

  const [mediaView, setMediaView] = useState<'rows' | 'grid'>(() => {
    try {
      const saved = localStorage.getItem('rt.media.view')
      return saved === 'grid' ? 'grid' : 'rows'
    } catch {
      return 'rows'
    }
  })

  const toggleMediaView = () => {
    setMediaView((prev) => {
      const next = prev === 'rows' ? 'grid' : 'rows'
      try {
        localStorage.setItem('rt.media.view', next)
      } catch {
        // Ignora errori di localStorage
      }
      return next
    })
  }

  const [autoPlaceMode, setAutoPlaceMode] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('rt-media-upload-mode')
      return saved !== 'pages_only'
    } catch {
      return true
    }
  })

  const toggleAutoPlaceMode = () => {
    setAutoPlaceMode((prev) => {
      const next = !prev
      try {
        localStorage.setItem('rt-media-upload-mode', next ? 'auto' : 'pages_only')
      } catch {
        // Ignora errori di localStorage
      }
      return next
    })
  }

  const fileInputRef = useRef<HTMLInputElement>(null)

  const closeUpload = () => {
    setOpenUpload(false)
    setUploadFiles([])
    setUploadError(null)
  }

  const removeUploadFile = (index: number) => {
    setUploadFiles((previous) => previous.filter((_, i) => i !== index))
  }

  const chooseUploadFiles = (files: File[]) => {
    const accepted = files.filter((file) => file.type.startsWith('image/') || file.type === 'application/pdf' ||
      ACCEPT.split(',').some((ext) => ext.startsWith('.') && file.name.toLowerCase().endsWith(ext)))
    const unsupported = files.find((file) => !accepted.includes(file))
    setUploadError(unsupported ? `Formato non supportato: ${unsupported.name}. Usa PDF o foto.` : null)
    setUploadFiles((previous) => [...previous, ...accepted])
  }

  useEffect(() => {
    const onMediaDrag = (e: Event) => {
      const custom = e as CustomEvent<{ active: boolean }>
      setMediaDragActive(Boolean(custom.detail?.active))
    }
    const onMediaDrop = (e: Event) => {
      const custom = e as CustomEvent<{ files: File[] }>
      if (custom.detail?.files?.length) {
        setOpenUpload(true)
        chooseUploadFiles(custom.detail.files)
      }
      setMediaDragActive(false)
    }
    const onCursorState = (e: Event) => {
      const custom = e as CustomEvent<{ hasCursor: boolean }>
      if (custom.detail !== undefined) {
        setCanInsertAtCursor(Boolean(custom.detail.hasCursor))
      }
    }
    const onMediaSelect = (e: Event) => {
      const custom = e as CustomEvent<{ name: string }>
      const name = custom.detail?.name
      if (!name) return
      const clean = name.split('#')[0]
      setSelectedNames(new Set([clean]))
    }
    window.addEventListener(ENRICHMENT_MEDIA_DRAG_EVENT, onMediaDrag)
    window.addEventListener(ENRICHMENT_MEDIA_DROP_EVENT, onMediaDrop)
    window.addEventListener('rt-editor-cursor-state', onCursorState)
    window.addEventListener('rt-media-select', onMediaSelect)
    window.dispatchEvent(new CustomEvent('rt-editor-request-cursor-state'))
    return () => {
      window.removeEventListener(ENRICHMENT_MEDIA_DRAG_EVENT, onMediaDrag)
      window.removeEventListener(ENRICHMENT_MEDIA_DROP_EVENT, onMediaDrop)
      window.removeEventListener('rt-editor-cursor-state', onCursorState)
      window.removeEventListener('rt-media-select', onMediaSelect)
    }
  }, [])

  if (!Number.isFinite(id)) return null

  const rawImageList = images.data?.images ?? []
  const elements = enrichment.data?.elements ?? []
  const completedElements = elements.filter(
    (e) => e.status === 'ready' || Boolean(e.asset_image),
  )

  const enrichmentImages: LessonImage[] = completedElements
    .filter((el) => !rawImageList.some((img) => el.asset_image && img.url.includes(el.asset_image.split('/').pop()!)))
    .map((el) => {
      const kindText = kindLabel(el.kind)
      const assetFileName = el.asset_image ? el.asset_image.split('/').pop()! : el.id
      return {
        name: assetFileName,
        url: el.asset_image ? assetUrl(id, el.asset_image) : '',
        source_name: 'Arricchimento',
        source: 'enrichment',
        alt_text: el.title || `${kindText} ${el.unit_id}`,
        slide_title: el.title || '',
        units: [el.unit_id],
        in_document: el.status !== 'dismissed',
        in_assets: true,
        page: null,
        descritta: true,
      }
    })

  // Media dell'arricchimento: si tolgono dal testo e si eliminano con le azioni dell'elemento.
  const enrichmentByName = new Map(completedElements.map((el) => [el.asset_image ? el.asset_image.split('/').pop()! : el.id, el]))

  const imageList: LessonImage[] = [...rawImageList, ...enrichmentImages].map((img) => {
    if (img.source === 'enrichment') return img
    const detected = findUnitForImage(img.name, docQuery.data?.markdown)
    const units = img.units && img.units.length > 0
      ? img.units
      : detected
        ? [detected]
        : (img.macro_ids ?? [])
    const inDoc = img.in_document || Boolean(detected)
    return {
      ...img,
      units,
      in_document: inDoc,
    }
  })

  const totalMedia = imageList.length
  const undescribedCount = imageList.filter((img) => !img.descritta).length
  const displayedImages = mediaFilter === 'undescribed' ? imageList.filter((img) => !img.descritta) : imageList
  const undescribedSelected = imageList.filter((img) => selectedNames.has(img.name) && !img.descritta)
  const canDescribe = undescribedSelected.length > 0
  const hasUsedSelected = imageList.some((img) => selectedNames.has(img.name) && img.in_document)

  let summaryText = '\u00a0'
  if (archiveSummary.data) {
    const { file, da_continuare } = archiveSummary.data
    const filePart = `${file} file`
    const continuePart = da_continuare > 0 ? `${da_continuare} PDF da continuare` : ''
    summaryText = continuePart ? `${filePart} · ${continuePart}` : filePart
  }

  const handleDescribe = async () => {
    const names = undescribedSelected.map((img) => img.name)
    if (!names.length) return
    try {
      const res = await describeMedia(id, names)
      setSelectedNames(new Set())
      if (res?.job_id) {
        setActiveJobId(res.job_id)
      } else {
        void refreshImages()
      }
    } catch {
      // Lezione occupata
    }
  }

  const handleCropNavigation = () => {
    const selected = imageList.find((i) => selectedNames.has(i.name))
    if (!selected) return
    let fileSha = ''
    let pageNumber = 1
    if (selected.source?.startsWith('material:')) {
      const parts = selected.source.split(':')
      const sourceId = parts[1]
      const src = sourcesQuery.data?.sources.find((s) => s.id === sourceId)
      fileSha = src?.impronta || ''
      pageNumber = selected.page ?? (parts[2] ? Number(parts[2]) : 1)
    } else if (selected.source?.startsWith('archive:')) {
      const parts = selected.source.split(':')
      fileSha = parts[1] || ''
      pageNumber = Number(parts[2]) || selected.page || 1
    } else {
      fileSha = selected.crop_of || selected.name.replace(/\.[^.]+$/, '')
      pageNumber = 1
    }
    navigate(`/archivio?da=${id}&file=${fileSha}&pagina=${pageNumber}&ritaglia=1`)
  }

  const handleOpenViewer = (flatIndex: number) => {
    const viewerImages = imageList.map((img) => ({
      src: img.url,
      alt: img.alt_text || img.name,
      docName: img.source_name || img.source || 'Media',
      pageNumber: img.page ?? undefined,
    }))
    window.dispatchEvent(
      new CustomEvent('rt-image-viewer-open', {
        detail: { images: viewerImages, index: flatIndex },
      }),
    )
  }

  const selectedEnrichment = Array.from(selectedNames).map((n) => enrichmentByName.get(n)).filter((el) => el !== undefined)
  // Un elemento dell'arricchimento torna nel testo al suo posto (in fondo all'unità).
  const restoreEnrichment = async () => {
    for (const el of selectedEnrichment) {
      if (el.status === 'dismissed') await action.mutateAsync({ element: el.id, action: 'restore' }).catch(() => undefined)
    }
  }

  const handleInsertAtCursor = async () => {
    await restoreEnrichment()
    const selected = imageList.filter((i) => selectedNames.has(i.name) && !enrichmentByName.has(i.name))
    if (!selected.length) {
      setSelectedNames(new Set())
      return
    }
    const items: Array<{ path: string; alt_text: string }> = []
    for (const img of selected) {
      if (!img.in_assets) {
        const sourceId = materialSourceId(img.source)
        if (!sourceId || img.page == null) continue
        try {
          const copied = await copyMaterialPage(id, sourceId, img.page)
          items.push({ path: copied.path, alt_text: copied.alt_text })
        } catch {
          // Pagina non copiata (job in corso): niente riferimento rotto nel testo.
        }
      } else {
        items.push({
          path: img.url.includes('/assets/images/')
            ? `assets/images/${img.url.split('/assets/images/').pop()}`
            : `assets/images/${img.name}`,
          alt_text: img.alt_text || img.name,
        })
      }
    }
    window.dispatchEvent(
      new CustomEvent('rt-editor-insert-images', { detail: { items } }),
    )
    setSelectedNames(new Set())
    void refreshImages()
  }

  const handleAutoPlace = () => {
    if (selectedNames.size === 0) return
    void restoreEnrichment()
    const names = Array.from(selectedNames).filter((n) => !enrichmentByName.has(n))
    if (!names.length) {
      setSelectedNames(new Set())
      return
    }
    addImages.mutate(
      { selected_images: names },
      {
        onSuccess: (res) => {
          setSelectedNames(new Set())
          if (res?.job_id) setActiveJobId(res.job_id)
        },
      },
    )
  }

  // Le pagine dei materiali (non copiate o copiate) si tolgono togliendo la fonte.
  const canDelete = imageList.some((img) => selectedNames.has(img.name) && img.in_assets && !img.source?.startsWith('material:'))

  const handleRemoveFromText = async () => {
    for (const el of selectedEnrichment) {
      if (el.status !== 'dismissed') await action.mutateAsync({ element: el.id, action: 'dismiss' }).catch(() => undefined)
    }
    const selected = imageList.filter((i) => selectedNames.has(i.name) && !enrichmentByName.has(i.name))
    const names = selected.map((s) => s.name)
    if (!names.length) {
      setSelectedNames(new Set())
      return
    }
    if (canInsertAtCursor) {
      // Editor aperto: il testo lo cambia l'editor e il salvataggio aggiorna il posizionamento.
      window.dispatchEvent(
        new CustomEvent('rt-editor-remove-images', { detail: { imageNames: names } }),
      )
    } else {
      try {
        await removeFromText(id, names)
      } catch {
        // Lezione occupata o in modifica altrove: il testo resta com'era.
      }
    }
    setSelectedNames(new Set())
    void refreshImages()
  }

  const handleDelete = async () => {
    setConfirmDelete(false)
    for (const el of selectedEnrichment) {
      await action.mutateAsync({ element: el.id, action: 'delete' }).catch(() => undefined)
    }
    const names = imageList
      .filter((i) => selectedNames.has(i.name) && !enrichmentByName.has(i.name) && i.in_assets && !i.source?.startsWith('material:'))
      .map((i) => i.name)
    if (names.length) {
      try {
        if (canInsertAtCursor) {
          // Editor aperto: il testo lo cambia l'editor, il server toglie posizionamento e file.
          window.dispatchEvent(new CustomEvent('rt-editor-remove-images', { detail: { imageNames: names } }))
          await deleteMedia(id, names, false)
        } else {
          await deleteMedia(id, names)
        }
      } catch {
        // Lezione occupata: i media restano.
      }
    }
    setSelectedNames(new Set())
    void refreshImages()
  }

  const visibleIdeas = elements.filter(
    (e) =>
      e.status !== 'ready' &&
      !e.asset_image &&
      e.status !== 'suppressed' &&
      (showIgnored ? true : e.status !== 'dismissed'),
  )
  const ignoredCount = elements.filter(
    (e) => e.status === 'dismissed' && !e.asset_image,
  ).length

  const handleUploadSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!uploadFiles.length) return
    addImages.mutate(
      { files: uploadFiles, perUnit: 0, units: null, pages_only: !autoPlaceMode },
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
    <div className="relative flex flex-col gap-4 text-body" data-testid="enrichment-panel">
      {mediaDragActive && (
        <div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-primary bg-primary/10 p-5 text-center font-semibold text-foreground pointer-events-none select-none animate-in fade-in duration-150"
          data-testid="enrichment-drop-veil"
          role="status"
          aria-live="polite"
        >
          <Upload className="size-8 text-primary" aria-hidden />
          <p>Rilascia per aggiungere ai media della lezione</p>
        </div>
      )}

      {/* Pulsante Archivio in cima al pannello */}
      <Button
        variant="outline"
        className="h-auto w-full min-w-0 justify-start gap-3 overflow-hidden py-3"
        onClick={() => navigate(`/archivio?da=${id}`)}
        data-testid="open-archive-button"
      >
        <Archive size={18} className="shrink-0" aria-hidden />
        <span className="flex min-w-0 flex-1 flex-col items-start">
          <span className="max-w-full truncate text-body font-medium">Archivio</span>
          <span className="max-w-full text-meta text-muted-foreground truncate">
            {summaryText}
          </span>
        </span>
      </Button>

      {/* Sezione Media della lezione */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">
              Media della lezione · {totalMedia}
            </h3>
            <div className="flex items-center gap-0.5">
              <IconButton
                label="Tutti"
                icon={LayoutGrid}
                active={mediaFilter === 'all'}
                className="size-7"
                data-testid="filter-all"
                onClick={() => setMediaFilter('all')}
              />
              <IconButton
                label={undescribedCount > 0 ? `Da descrivere (${undescribedCount})` : 'Da descrivere'}
                icon={CircleDot}
                active={mediaFilter === 'undescribed'}
                className="size-7 relative"
                data-testid="filter-undescribed"
                badge={
                  undescribedCount > 0 ? (
                    <span
                      className="absolute -top-0.5 -right-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-warning px-1 text-[9px] font-bold text-foreground"
                      data-testid="undescribed-count"
                    >
                      {undescribedCount}
                    </span>
                  ) : null
                }
                onClick={() => setMediaFilter('undescribed')}
              />
            </div>
          </div>
          <div className="flex items-center gap-1">
            <IconButton
              label={mediaView === 'rows' ? 'Vista a griglia' : 'Una pagina per riga'}
              icon={mediaView === 'rows' ? LayoutGrid : Rows3}
              className="size-7"
              onClick={toggleMediaView}
            />
            <IconButton
              label="Aggiungi immagini (PDF o foto)"
              icon={Upload}
              className="size-7"
              active={openUpload}
              onClick={() => {
                if (openUpload) {
                  closeUpload()
                } else {
                  setOpenUpload(true)
                  setOpenSearch(false)
                }
              }}
            />
            <IconButton
              label="Cerca immagini sul web"
              icon={Search}
              className="size-7"
              active={openSearch}
              onClick={() => {
                setOpenSearch(!openSearch)
                closeUpload()
              }}
            />
          </div>
        </div>

        {/* Scheda Aggiungi immagini */}
        {openUpload && (
          <Card
            data-file-drop-target
            data-testid="enrichment-upload"
            className={cn('relative flex flex-col gap-2.5 p-3 overflow-hidden', draggingUpload && 'border-foreground bg-muted')}
            onDragOver={(event) => {
              if (!Array.from(event.dataTransfer.types).includes('Files')) return
              event.preventDefault()
              setDraggingUpload(true)
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDraggingUpload(false)
            }}
            onDrop={(event) => {
              event.preventDefault()
              setDraggingUpload(false)
              chooseUploadFiles(Array.from(event.dataTransfer.files))
            }}
          >
            {draggingUpload && (
              <div
                className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-primary/10 p-6 text-center font-medium text-foreground pointer-events-none"
                data-testid="enrichment-upload-drop-zone"
              >
                <ScanEye className="size-8 text-primary" aria-hidden />
                <span>Analizza e aggiungi</span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-body font-semibold">Aggiungi PDF o foto</span>
              <IconButton label="Chiudi" icon={X} className="size-6" onClick={closeUpload} />
            </div>
            <form onSubmit={handleUploadSubmit} className="flex flex-col gap-2.5">
              <input
                ref={fileInputRef}
                type="file"
                hidden
                multiple
                accept={ACCEPT}
                aria-label="PDF o foto"
                onChange={(e) => {
                  chooseUploadFiles(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="size-4" aria-hidden />
                  {uploadFiles.length === 0 ? 'Scegli file' : 'Aggiungi altri'}
                </Button>
                {uploadFiles.length === 0 && (
                  <span className="text-meta text-muted-foreground">oppure trascinali qui</span>
                )}
              </div>
              {uploadFiles.length > 0 && (
                <ul aria-label="File scelti" className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                  {uploadFiles.map((file, index) => {
                    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
                    return (
                      <li
                        key={`${file.name}-${index}`}
                        className="flex items-center justify-between gap-2 rounded-md border border-border/60 bg-muted/30 px-2 py-1 text-meta"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          {isPdf ? (
                            <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                          ) : (
                            <Image className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                          )}
                          <span className="truncate" title={file.name}>
                            {file.name}
                          </span>
                          <span className="shrink-0 text-muted-foreground">
                            {formatBytes(file.size)}
                          </span>
                        </div>
                        <IconButton
                          label={`Rimuovi ${file.name}`}
                          icon={X}
                          className="size-6 shrink-0"
                          onClick={() => removeUploadFile(index)}
                        />
                      </li>
                    )
                  })}
                </ul>
              )}
              {uploadError && <Alert tone="danger">{uploadError}</Alert>}
              <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-muted/30 p-2">
                <Tooltip
                  content={autoPlaceMode ? 'Clic per tenere solo le pagine' : 'Clic per collocarle in automatico'}
                  side="top"
                >
                  {(trigger) => (
                    <button
                      type="button"
                      aria-pressed={autoPlaceMode}
                      aria-label={
                        autoPlaceMode
                          ? 'Collocazione automatica: clic per tenere solo le pagine'
                          : 'Solo pagine: clic per collocarle in automatico'
                      }
                      className={cn(
                        'flex size-8 shrink-0 items-center justify-center rounded-md border transition-colors cursor-pointer',
                        autoPlaceMode
                          ? 'border-accent/40 bg-accent/15 text-accent-foreground'
                          : 'border-border bg-background text-muted-foreground hover:text-foreground',
                      )}
                      {...trigger}
                      onClick={toggleAutoPlaceMode}
                    >
                      {autoPlaceMode ? (
                        <Sparkles className="size-4" aria-hidden />
                      ) : (
                        <Layers className="size-4" aria-hidden />
                      )}
                    </button>
                  )}
                </Tooltip>
                <p className="text-meta text-muted-foreground leading-snug">
                  {autoPlaceMode
                    ? 'Le pagine vengono descritte e collocate in automatico nelle sottounità.'
                    : 'Le pagine restano nei media: le inserisci tu, o le fai collocare dopo.'}
                </p>
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <Button size="sm" variant="ghost" type="button" onClick={closeUpload}>
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
        {/* Popup centrale: l'elenco delle unità non esce dal pannello. */}
        <Modal open={openSearch} onClose={() => setOpenSearch(false)} title="Cerca immagini sul web" testId="image-search-dialog" className="w-[min(440px,calc(100vw-32px))]">
              <form onSubmit={handleSearchSubmit} className="mt-3 flex min-w-0 flex-col gap-2.5">
                <div className="flex flex-wrap items-center gap-2">
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

                <div className="flex flex-wrap items-center gap-3 text-meta">
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
                  <fieldset className="min-w-0 max-h-60 overflow-y-auto rounded-md border p-2 text-meta">
                    <legend className="px-1 text-muted-foreground">Unità selezionate</legend>
                    {outline.data.macro_sections.flatMap((m) =>
                      m.units.map((u) => (
                        <label key={u.id} className="flex min-w-0 items-center gap-2 py-0.5" title={`${u.id} ${u.title}`}>
                          <input
                            className="shrink-0"
                            type="checkbox"
                            checked={selectedUnits.has(u.id)}
                            onChange={(e) => {
                              const next = new Set(selectedUnits)
                              if (e.target.checked) next.add(u.id)
                              else next.delete(u.id)
                              setSelectedUnits(next)
                            }}
                          />
                          <span className="min-w-0 flex-1 truncate">
                            {u.id} {u.title}
                          </span>
                        </label>
                      )),
                    )}
                  </fieldset>
                )}

                <div className="flex flex-wrap justify-end gap-2 pt-1">
                  <Button size="sm" variant="ghost" type="button" onClick={() => setOpenSearch(false)}>
                    Annulla
                  </Button>
                  <Button size="sm" variant="default" type="submit" disabled={addImages.isPending}>
                    Cerca
                  </Button>
                </div>
              </form>
        </Modal>

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
        {displayedImages.length > 0 && (
          <MediaGallery
            lessonId={id}
            images={displayedImages}
            selectedNames={selectedNames}
            view={mediaView}
            onToggleSelect={(name) =>
              setSelectedNames((prev) => {
                const next = new Set(prev)
                if (next.has(name)) next.delete(name)
                else next.add(name)
                return next
              })
            }
            onSelectRange={(names) =>
              setSelectedNames((prev) => new Set([...prev, ...names]))
            }
            onSelectGroup={(groupImages) => {
              const allIn =
                groupImages.length > 0 &&
                groupImages.every((i) => selectedNames.has(i.name))
              setSelectedNames((prev) => {
                const next = new Set(prev)
                for (const i of groupImages) {
                  if (allIn) next.delete(i.name)
                  else next.add(i.name)
                }
                return next
              })
            }}
            onSelectAll={() => setSelectedNames(new Set(displayedImages.map((i) => i.name)))}
            onClearSelection={() => setSelectedNames(new Set())}
            onOpenViewer={handleOpenViewer}
            onScrollToMedia={scrollToMedia}
          />
        )}

        {displayedImages.length === 0 && (
          <p className="py-2 text-center text-meta text-muted-foreground">
            {totalMedia === 0 ? 'Nessun media presente nella lezione.' : 'Tutte le immagini sono descritte.'}
          </p>
        )}

        <MediaSelectionBar
          selectedCount={selectedNames.size}
          canDescribe={canDescribe}
          canInsertAtCursor={canInsertAtCursor}
          hasUsedSelected={hasUsedSelected}
          canDelete={canDelete}
          onDescribe={handleDescribe}
          onAutoPlace={handleAutoPlace}
          onInsertAtCursor={handleInsertAtCursor}
          onCrop={handleCropNavigation}
          onRemoveFromText={handleRemoveFromText}
          onDelete={() => setConfirmDelete(true)}
          onSelectAll={() => setSelectedNames(new Set(imageList.map((i) => i.name)))}
          onClearSelection={() => setSelectedNames(new Set())}
        />
        <ConfirmDialog
          open={confirmDelete}
          title="Eliminare dalla lezione?"
          confirmLabel="Elimina"
          onConfirm={() => void handleDelete()}
          onCancel={() => setConfirmDelete(false)}
        >
          Spariscono dal testo e dalla lezione.
        </ConfirmDialog>
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
                {e.status !== 'ready' && !e.asset_image && (
                  <Button
                    size="sm"
                    variant="default"
                    disabled={generate.isPending}
                    onClick={() => generate.mutate({ element_id: e.id })}
                  >
                    <Sparkles className="size-3" /> Genera
                  </Button>
                )}
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
