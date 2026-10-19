import { CheckSquare, ChevronDown, Scissors } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

import type { LessonImage } from '@/api/images'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { groupMediaImages } from './mediaGalleryUtils'

interface MediaGalleryProps {
  lessonId?: number
  images: LessonImage[]
  selectedNames: Set<string>
  view?: 'rows' | 'grid'
  onToggleSelect: (name: string) => void
  onSelectRange: (names: string[]) => void
  onSelectGroup: (groupImages: LessonImage[]) => void
  onSelectAll: () => void
  onClearSelection: () => void
  onOpenViewer: (flatIndex: number) => void
  onCrop: (image: LessonImage) => void
  onScrollToMedia?: (target: { imageName?: string | null; unitId?: string | null }) => void
}

interface MediaCellProps {
  img: LessonImage
  flatIndex: number
  isSelected: boolean
  view: 'rows' | 'grid'
  lessonId?: number
  isPeekActive?: boolean
  onImageClick: (img: LessonImage, flatIndex: number, shiftKey: boolean) => void
  onOpenViewer: (flatIndex: number) => void
  startLongPress: (index: number) => void
  cancelLongPress: () => void
  onCrop: (image: LessonImage) => void
  onPointerDown: (
    e: React.PointerEvent,
    img: LessonImage,
    captionLabel: string,
    unitText: string | null,
  ) => void
  onPointerMove: (e: React.PointerEvent) => void
  cancelPeekTimer: () => void
}

function MediaCell({
  img,
  flatIndex,
  isSelected,
  view,
  lessonId,
  isPeekActive,
  onImageClick,
  onOpenViewer,
  startLongPress,
  cancelLongPress,
  onCrop,
  onPointerDown,
  onPointerMove,
  cancelPeekTimer,
}: MediaCellProps) {
  const unitText = img.units && img.units.length > 0 ? img.units.join(', ') : null

  let captionLabel: string
  if (img.crop_index) {
    captionLabel = `Pag. ${img.page} · ritaglio ${img.crop_index}`
  } else if (img.page != null) {
    captionLabel = `Pag. ${img.page}`
  } else {
    captionLabel = img.alt_text || 'Immagine'
  }

  let ariaLabel: string
  if (img.page != null) {
    ariaLabel = `Pagina ${img.page}${img.in_document && unitText ? ', usata in ' + unitText : ', non usata'}`
  } else {
    const unitLabel = unitText ?? (img.source === 'pdf' ? 'da PDF' : 'non assegnata')
    ariaLabel = captionLabel.includes(unitLabel)
      ? `${captionLabel}: vai nel testo`
      : `${captionLabel} ${unitLabel}: vai nel testo`
  }

  return (
    <div
      className={cn('group relative flex flex-col gap-1 min-w-0', view === 'rows' && 'w-full')}
      data-testid={`media-cell-${img.name}`}
    >
      <button
        type="button"
        draggable
        onDragStart={(e) => {
          cancelPeekTimer()
          if (isPeekActive) {
            e.preventDefault()
            return
          }
          e.dataTransfer.setData(
            'application/x-rt-media-image',
            JSON.stringify({
              path: img.in_assets ? `assets/images/${img.name}` : img.url,
              alt_text:
                img.alt_text ||
                (img.page ? `${img.source_name}, pagina ${img.page}` : img.name),
              source_name: img.source_name,
              source: img.source,
              page: img.page,
              in_assets: img.in_assets,
              lessonId,
            }),
          )
          e.dataTransfer.effectAllowed = 'copy'
        }}
        aria-label={ariaLabel}
        aria-pressed={isSelected}
        className={cn(
          'relative w-full rounded-lg border bg-muted overflow-hidden cursor-pointer transition-all',
          view === 'rows' ? 'aspect-video' : 'aspect-[4/3]',
          !img.in_document && !isSelected && 'opacity-70 hover:opacity-100',
          isSelected
            ? 'outline-2 outline-primary outline-offset-1 border-primary ring-2 ring-primary/20'
            : 'hover:border-foreground/40',
        )}
        onPointerDown={(e) => onPointerDown(e, img, captionLabel, unitText)}
        onPointerMove={onPointerMove}
        onPointerUp={cancelPeekTimer}
        onPointerLeave={cancelPeekTimer}
        onClick={(e) => onImageClick(img, flatIndex, e.shiftKey)}
        onDoubleClick={() => onOpenViewer(flatIndex)}
        onTouchStart={() => startLongPress(flatIndex)}
        onTouchEnd={cancelLongPress}
        onTouchMove={cancelLongPress}
      >
        <img
          src={img.url}
          alt={img.alt_text || img.name}
          className="size-full object-contain pointer-events-none select-none"
          loading="lazy"
        />
        <span
          className={cn(
            'absolute left-1.5 top-1.5 flex size-4.5 items-center justify-center rounded-full text-[11px] font-bold transition-opacity',
            isSelected
              ? 'bg-primary text-primary-foreground opacity-100'
              : 'bg-black/45 text-white opacity-0 group-hover:opacity-100',
          )}
          aria-hidden
        >
          ✓
        </span>
        {Boolean(img.crop_of || img.crop_index) && (
          <span
            className="absolute right-1.5 bottom-1.5 flex size-5 items-center justify-center rounded-md bg-accent text-accent-foreground shadow-sm pointer-events-none"
            data-testid="crop-badge"
            aria-label="Ritaglio"
          >
            <Scissors className="size-3" aria-hidden />
          </span>
        )}
      </button>

      <Tooltip content="Ritaglia" side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label={`Ritaglia ${img.page ? 'la pagina ' + img.page : 'l\'immagine'}`}
            className="absolute right-1 top-1 flex size-6 items-center justify-center rounded-md bg-black/60 text-white opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity hover:bg-black/85 cursor-pointer z-10 [@media(hover:none)]:opacity-100"
            {...trigger}
            onClick={(e) => {
              e.stopPropagation()
              onCrop(img)
            }}
          >
            <Scissors className="size-3.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {view === 'rows' ? (
        <div className="flex items-center justify-between gap-2 text-meta text-muted-foreground tabular-nums">
          <span className="shrink-0">{captionLabel}</span>
          <span className="truncate text-right">
            {img.in_document && unitText ? (
              <b className="font-semibold text-foreground">{unitText}</b>
            ) : (
              'non usata'
            )}
          </span>
        </div>
      ) : (
        <span className="truncate text-meta text-muted-foreground font-mono tabular-nums">
          {captionLabel} ·{' '}
          {img.in_document && unitText ? (
            <b className="font-semibold text-foreground">{unitText}</b>
          ) : (
            'non usata'
          )}
        </span>
      )}
    </div>
  )
}

export function MediaGallery({
  lessonId,
  images,
  selectedNames,
  view = 'rows',
  onToggleSelect,
  onSelectRange,
  onSelectGroup,
  onSelectAll,
  onClearSelection,
  onOpenViewer,
  onCrop,
  onScrollToMedia,
}: MediaGalleryProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const lastClickedIndexRef = useRef<number | null>(null)
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [peek, setPeek] = useState<{ img: LessonImage; captionLabel: string; unitText: string | null } | null>(null)
  const peekTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pointerStartPosRef = useRef<{ x: number; y: number } | null>(null)
  const peekShownRef = useRef<boolean>(false)

  const cancelPeekTimer = useCallback(() => {
    if (peekTimerRef.current) {
      clearTimeout(peekTimerRef.current)
      peekTimerRef.current = null
    }
    pointerStartPosRef.current = null
  }, [])

  useEffect(() => {
    if (!peek) return

    const closePeek = () => {
      setPeek(null)
    }

    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        closePeek()
      }
    }

    window.addEventListener('pointerup', closePeek)
    window.addEventListener('blur', closePeek)
    window.addEventListener('keydown', onKeyDown)

    return () => {
      window.removeEventListener('pointerup', closePeek)
      window.removeEventListener('blur', closePeek)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [peek])

  const handlePointerDown = useCallback((
    e: React.PointerEvent,
    img: LessonImage,
    captionLabel: string,
    unitText: string | null,
  ) => {
    if (view !== 'grid') return
    if (e.pointerType !== 'mouse' || e.button !== 0 || e.shiftKey || e.metaKey || e.ctrlKey) return

    cancelPeekTimer()
    pointerStartPosRef.current = { x: e.clientX, y: e.clientY }

    peekTimerRef.current = setTimeout(() => {
      setPeek({ img, captionLabel, unitText })
      peekShownRef.current = true
      peekTimerRef.current = null
    }, 350)
  }, [view, cancelPeekTimer])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!pointerStartPosRef.current || !peekTimerRef.current) return
    const dx = Math.abs(e.clientX - pointerStartPosRef.current.x)
    const dy = Math.abs(e.clientY - pointerStartPosRef.current.y)
    if (dx > 5 || dy > 5) {
      cancelPeekTimer()
    }
  }, [cancelPeekTimer])

  const groups = groupMediaImages(images)
  const flatImages = groups.flatMap((g) => g.images)

  const toggleGroup = useCallback((groupName: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupName)) next.delete(groupName)
      else next.add(groupName)
      return next
    })
  }, [])

  const handleImageClick = (img: LessonImage, flatIndex: number, shiftKey: boolean) => {
    if (peekShownRef.current) {
      peekShownRef.current = false
      return
    }
    if (shiftKey && lastClickedIndexRef.current !== null) {
      const start = Math.min(lastClickedIndexRef.current, flatIndex)
      const end = Math.max(lastClickedIndexRef.current, flatIndex)
      const rangeNames = flatImages.slice(start, end + 1).map((i) => i.name)
      onSelectRange(rangeNames)
    } else {
      onToggleSelect(img.name)
    }
    lastClickedIndexRef.current = flatIndex
    if (onScrollToMedia && img.in_document) {
      const targetUnit = img.units?.[0] ?? null
      onScrollToMedia({ imageName: img.name, unitId: targetUnit })
    }
  }

  const handleDoubleClick = (flatIndex: number) => {
    if (peekShownRef.current) {
      peekShownRef.current = false
      return
    }
    onOpenViewer(flatIndex)
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault()
      onSelectAll()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClearSelection()
    }
  }

  const startLongPress = (index: number) => {
    if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current)
    longPressTimerRef.current = setTimeout(() => {
      onOpenViewer(index)
    }, 500)
  }

  const cancelLongPress = () => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }

  return (
    <div
      className="flex flex-col gap-3 outline-none"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      role="region"
      aria-label="Galleria media della lezione"
      data-testid="media-gallery"
    >
      {groups.map((group) => {
        const isOpen = !collapsedGroups.has(group.name)
        const groupFlatStartIndex = group.flatStartIndex

        return (
          <div key={group.name} className="flex flex-col gap-2" data-testid={`media-group-${group.name}`}>
            {/* Header del gruppo */}
            <div className="flex items-center justify-between gap-1">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-meta font-semibold text-foreground hover:text-primary transition-colors cursor-pointer"
                aria-expanded={isOpen}
                onClick={() => toggleGroup(group.name)}
              >
                <ChevronDown
                  className={cn('size-3.5 shrink-0 transition-transform duration-150', !isOpen && '-rotate-90')}
                  aria-hidden
                />
                <span className="truncate">{group.name}</span>
                <span className="shrink-0 text-meta font-normal text-muted-foreground tabular-nums">
                  {group.usedCount > 0
                    ? `${group.usedCount} usate su ${group.totalCount}`
                    : `${group.totalCount} pagine`}
                </span>
              </button>

              <Tooltip content="Seleziona tutte le pagine di questa fonte" side="top">
                {(trigger) => (
                  <button
                    type="button"
                    aria-label="Seleziona tutte le pagine di questa fonte"
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors"
                    {...trigger}
                    onClick={() => onSelectGroup(group.images)}
                  >
                    <CheckSquare className="size-4" aria-hidden />
                  </button>
                )}
              </Tooltip>
            </div>

            {/* Miniature */}
            {isOpen && (
              <div
                className={cn('pt-0.5', view === 'rows' ? 'flex flex-col gap-3' : 'grid grid-cols-3 gap-2.5')}
                role="group"
                aria-label={group.name}
              >
                {group.images.map((img, idxInGroup) => {
                  const flatIndex = groupFlatStartIndex + idxInGroup
                  const isSelected = selectedNames.has(img.name)

                  return (
                    <MediaCell
                      key={img.name}
                      img={img}
                      flatIndex={flatIndex}
                      isSelected={isSelected}
                      view={view}
                      lessonId={lessonId}
                      isPeekActive={Boolean(peek)}
                      onImageClick={handleImageClick}
                      onOpenViewer={handleDoubleClick}
                      startLongPress={startLongPress}
                      cancelLongPress={cancelLongPress}
                      onCrop={onCrop}
                      onPointerDown={handlePointerDown}
                      onPointerMove={handlePointerMove}
                      cancelPeekTimer={cancelPeekTimer}
                    />
                  )
                })}
              </div>
            )}
          </div>
        )
      })}

      {peek &&
        createPortal(
          <div
            role="dialog"
            aria-label={
              peek.img.page != null
                ? `Anteprima pagina ${peek.img.page}`
                : `Anteprima ${peek.captionLabel}`
            }
            className="fixed inset-0 z-50 flex flex-col items-center justify-center p-4 bg-black/40 pointer-events-none animate-in fade-in zoom-in-95 duration-100"
          >
            <div className="flex flex-col items-center gap-2">
              <img
                src={peek.img.url}
                alt={peek.img.alt_text || peek.img.name}
                className="max-w-[min(90vw,1100px)] max-h-[80vh] object-contain rounded-lg shadow-2xl bg-background"
              />
              <div className="flex items-center gap-2 text-body text-white">
                <span>{peek.captionLabel}</span>
                <span>·</span>
                {peek.img.in_document && peek.unitText ? (
                  <b className="font-semibold text-white">{peek.unitText}</b>
                ) : (
                  <span>non usata</span>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
