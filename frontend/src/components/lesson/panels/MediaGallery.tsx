import { CheckSquare, ChevronDown, Scissors } from 'lucide-react'
import { useCallback, useRef, useState, type KeyboardEvent } from 'react'

import type { LessonImage } from '@/api/images'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { groupMediaImages } from './mediaGalleryUtils'

interface MediaGalleryProps {
  lessonId?: number
  images: LessonImage[]
  selectedNames: Set<string>
  onToggleSelect: (name: string) => void
  onSelectRange: (names: string[]) => void
  onSelectGroup: (groupImages: LessonImage[]) => void
  onSelectAll: () => void
  onClearSelection: () => void
  onOpenViewer: (flatIndex: number) => void
  onCrop: (image: LessonImage) => void
  onScrollToMedia?: (target: { imageName?: string | null; unitId?: string | null }) => void
}

export function MediaGallery({
  lessonId,
  images,
  selectedNames,
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

            {/* Griglia miniature */}
            {isOpen && (
              <div className="grid grid-cols-3 gap-2.5 pt-0.5" role="group" aria-label={group.name}>
                {group.images.map((img, idxInGroup) => {
                  const flatIndex = groupFlatStartIndex + idxInGroup
                  const isSelected = selectedNames.has(img.name)
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
                      key={img.name}
                      className="group relative flex flex-col gap-1 min-w-0"
                      data-testid={`media-cell-${img.name}`}
                    >
                      <button
                        type="button"
                        draggable
                        onDragStart={(e) => {
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
                          'relative aspect-[4/3] w-full rounded-lg border bg-muted overflow-hidden cursor-pointer transition-all',
                          !img.in_document && !isSelected && 'opacity-70 hover:opacity-100',
                          isSelected
                            ? 'outline-2 outline-primary outline-offset-1 border-primary ring-2 ring-primary/20'
                            : 'hover:border-foreground/40',
                        )}
                        onClick={(e) => handleImageClick(img, flatIndex, e.shiftKey)}
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

                      <span className="truncate text-meta text-muted-foreground font-mono tabular-nums">
                        {captionLabel} ·{' '}
                        {img.in_document && unitText ? (
                          <b className="font-semibold text-foreground">{unitText}</b>
                        ) : (
                          'non usata'
                        )}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
