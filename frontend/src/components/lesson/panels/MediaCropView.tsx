import { AlertTriangle, Maximize2, RefreshCcw, Scissors, X } from 'lucide-react'
import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Modal } from '@/components/ui/modal'
import { Tooltip } from '@/components/ui/tooltip'
import type { LessonImage } from '@/api/images'

interface MediaCropViewProps {
  image: LessonImage
  onClose: () => void
  onSave: (rect: [number, number, number, number], replace: boolean) => Promise<void> | void
  isPending?: boolean
}

export function MediaCropView({ image, onClose, onSave, isPending }: MediaCropViewProps) {
  // rect: [left, top, width, height] in 0.0 - 1.0 relative coords
  const [rect, setRect] = useState<[number, number, number, number]>([0.08, 0.15, 0.65, 0.45])
  const [showReplaceModal, setShowReplaceModal] = useState(false)

  const stageRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    handle: string
    startX: number
    startY: number
    startLeft: number
    startTop: number
    startWidth: number
    startHeight: number
    stageWidth: number
    stageHeight: number
  } | null>(null)

  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!stageRef.current) return
    const stageRect = stageRef.current.getBoundingClientRect()
    const target = e.target as HTMLElement
    const handle = target.dataset.h || 'move'

    const currentLeft = rect[0] * stageRect.width
    const currentTop = rect[1] * stageRect.height
    const currentWidth = rect[2] * stageRect.width
    const currentHeight = rect[3] * stageRect.height

    dragRef.current = {
      handle,
      startX: e.clientX,
      startY: e.clientY,
      startLeft: currentLeft,
      startTop: currentTop,
      startWidth: currentWidth,
      startHeight: currentHeight,
      stageWidth: stageRect.width,
      stageHeight: stageRect.height,
    }

    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return

    const dx = e.clientX - drag.startX
    const dy = e.clientY - drag.startY
    let l = drag.startLeft
    let t = drag.startTop
    let w = drag.startWidth
    let h = drag.startHeight
    const minSize = 24

    if (drag.handle === 'move') {
      l = Math.max(0, Math.min(drag.stageWidth - w, l + dx))
      t = Math.max(0, Math.min(drag.stageHeight - h, t + dy))
    } else {
      if (drag.handle.includes('w')) {
        const nl = Math.max(0, Math.min(l + w - minSize, l + dx))
        w += l - nl
        l = nl
      }
      if (drag.handle.includes('e')) {
        w = Math.max(minSize, Math.min(drag.stageWidth - l, w + dx))
      }
      if (drag.handle.includes('n')) {
        const nt = Math.max(0, Math.min(t + h - minSize, t + dy))
        h += t - nt
        t = nt
      }
      if (drag.handle.includes('s')) {
        h = Math.max(minSize, Math.min(drag.stageHeight - t, h + dy))
      }
    }

    const nextRect: [number, number, number, number] = [
      Math.max(0, Math.min(1, l / drag.stageWidth)),
      Math.max(0, Math.min(1, t / drag.stageHeight)),
      Math.max(0.01, Math.min(1, w / drag.stageWidth)),
      Math.max(0.01, Math.min(1, h / drag.stageHeight)),
    ]
    setRect(nextRect)
  }

  const handlePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = null
    try {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
    } catch {
      // ignore
    }
  }

  const handleResetFullPage = useCallback(() => {
    setRect([0, 0, 1, 1])
  }, [])

  const handleSaveNew = async () => {
    await onSave(rect, false)
  }

  const handleConfirmReplace = async () => {
    setShowReplaceModal(false)
    await onSave(rect, true)
  }

  const title = image.page != null ? `Pagina ${image.page}` : image.alt_text || image.name
  const subtitle = image.alt_text || image.source_name

  const unitsText = image.units && image.units.length > 0 ? image.units.join(' e ') : null

  return (
    <Card className="flex flex-col gap-3 p-3.5 animate-in fade-in duration-150" data-testid="media-crop-view">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="text-body font-semibold truncate">{title}</span>
          {subtitle && subtitle !== title && (
            <span className="text-meta text-muted-foreground truncate">{subtitle}</span>
          )}
        </div>
        <Tooltip content="Chiudi ritaglio" side="bottom">
          {(trigger) => (
            <button
              type="button"
              aria-label="Chiudi ritaglio"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors"
              {...trigger}
              onClick={onClose}
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </Tooltip>
      </div>

      {/* Area del ritaglio */}
      <div
        ref={stageRef}
        className="relative aspect-[4/3] w-full max-w-full overflow-hidden rounded-lg bg-neutral-900 select-none touch-none"
        data-testid="crop-stage"
      >
        <img
          src={image.url}
          alt={image.alt_text || image.name}
          className="size-full object-contain pointer-events-none select-none"
          draggable={false}
        />

        {/* Bounding box interattivo */}
        <div
          role="region"
          aria-label="Riquadro di ritaglio"
          tabIndex={0}
          className="absolute border-2 border-white shadow-[0_0_0_9999px_rgba(0,0,0,0.55)] cursor-move select-none"
          style={{
            left: `${rect[0] * 100}%`,
            top: `${rect[1] * 100}%`,
            width: `${rect[2] * 100}%`,
            height: `${rect[3] * 100}%`,
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {/* 4 maniglie d'angolo */}
          <span
            data-h="nw"
            aria-label="Maniglia nord-ovest"
            className="absolute -left-2 -top-2 size-4 rounded-full border-2 border-accent bg-white cursor-nwse-resize"
          />
          <span
            data-h="ne"
            aria-label="Maniglia nord-est"
            className="absolute -right-2 -top-2 size-4 rounded-full border-2 border-accent bg-white cursor-nesw-resize"
          />
          <span
            data-h="sw"
            aria-label="Maniglia sud-ovest"
            className="absolute -left-2 -bottom-2 size-4 rounded-full border-2 border-accent bg-white cursor-nesw-resize"
          />
          <span
            data-h="se"
            aria-label="Maniglia sud-est"
            className="absolute -right-2 -bottom-2 size-4 rounded-full border-2 border-accent bg-white cursor-nwse-resize"
          />
        </div>
      </div>

      {/* Barra delle azioni: solo icone con tooltip di RT */}
      <div className="flex items-center justify-end gap-1.5 pt-1">
        <Tooltip content="Annulla" side="top">
          {(trigger) => (
            <button
              type="button"
              aria-label="Annulla ritaglio"
              className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors"
              {...trigger}
              onClick={onClose}
              disabled={isPending}
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </Tooltip>

        <Tooltip content="Pagina intera" side="top">
          {(trigger) => (
            <button
              type="button"
              aria-label="Pagina intera"
              className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors"
              {...trigger}
              onClick={handleResetFullPage}
              disabled={isPending}
            >
              <Maximize2 className="size-4" aria-hidden />
            </button>
          )}
        </Tooltip>

        <Tooltip content="Sostituisci la pagina con il ritaglio" side="top">
          {(trigger) => (
            <button
              type="button"
              aria-label="Sostituisci la pagina con il ritaglio"
              className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors"
              {...trigger}
              onClick={() => setShowReplaceModal(true)}
              disabled={isPending}
            >
              <RefreshCcw className="size-4" aria-hidden />
            </button>
          )}
        </Tooltip>

        <Tooltip content="Salva come nuova immagine" side="top">
          {(trigger) => (
            <button
              type="button"
              aria-label="Salva come nuova immagine"
              className="flex size-8 items-center justify-center rounded-lg border border-accent/40 bg-accent text-accent-foreground hover:bg-accent/90 cursor-pointer transition-colors"
              {...trigger}
              onClick={handleSaveNew}
              disabled={isPending}
            >
              <Scissors className="size-4" aria-hidden />
            </button>
          )}
        </Tooltip>
      </div>

      {/* Popup di conferma per 'Sostituisci la pagina' */}
      <Modal
        open={showReplaceModal}
        onClose={() => setShowReplaceModal(false)}
        title={`Sostituire la pagina ${image.page ?? ''} con il ritaglio?`}
        testId="replace-crop-dialog"
      >
        <div className="flex flex-col gap-3 pt-1">
          <p className="text-body text-muted-foreground">
            L&apos;immagine intera della pagina {image.page ?? ''} viene sostituita dal ritaglio e non si potrà
            ripristinare da qui.
          </p>

          <Alert tone="warning" className="text-meta">
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            <span>
              {unitsText
                ? `È nel testo delle unità ${unitsText}: lì comparirà il ritaglio.`
                : 'Non compare attualmente nel testo della lezione.'}
            </span>
          </Alert>

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowReplaceModal(false)}
              disabled={isPending}
            >
              Annulla
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleConfirmReplace}
              disabled={isPending}
            >
              Sostituisci
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  )
}
