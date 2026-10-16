import { useEffect, useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import {
  ENRICHMENT_MEDIA_DRAG_EVENT,
  ENRICHMENT_MEDIA_DROP_EVENT,
  hasAcceptedDrag,
  isAcceptedFile,
  isEnrichmentPanelOpen,
  isExcludedTarget,
  isMediaFile,
  isMediaOnlyDrag,
} from './globalFileDropUtils'

const DRAG_IDLE_MS = 700

export function GlobalFileDrop({
  disabled,
  onDropFiles,
}: {
  disabled?: boolean
  onDropFiles: (files: File[]) => void
}) {
  const [active, setActive] = useState(false)
  const [excluded, setExcluded] = useState(false)
  // Il velo resta finché arrivano dragover (il browser li manda di continuo, anche a mouse
  // fermo): si chiude al rilascio, con Esc, quando il trascinamento esce dalla finestra o
  // quando i dragover smettono. I dragleave fra un elemento e l'altro della pagina non
  // contano (Safari li manda con relatedTarget null a ogni passaggio).
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (disabled) return

    const close = () => {
      if (idleTimer.current) clearTimeout(idleTimer.current)
      idleTimer.current = null
      setActive(false)
      setExcluded(false)
      window.dispatchEvent(new CustomEvent(ENRICHMENT_MEDIA_DRAG_EVENT, { detail: { active: false } }))
    }

    const keepOpen = (e: DragEvent) => {
      const isMediaDragForEnrichment =
        e.dataTransfer ? isEnrichmentPanelOpen() && isMediaOnlyDrag(e.dataTransfer) : false

      if (isMediaDragForEnrichment) {
        setActive(false)
        setExcluded(false)
        window.dispatchEvent(new CustomEvent(ENRICHMENT_MEDIA_DRAG_EVENT, { detail: { active: true } }))
      } else {
        setActive(true)
        setExcluded(isExcludedTarget((e.target as Element | null) ?? null))
        window.dispatchEvent(new CustomEvent(ENRICHMENT_MEDIA_DRAG_EVENT, { detail: { active: false } }))
      }
      if (idleTimer.current) clearTimeout(idleTimer.current)
      idleTimer.current = setTimeout(close, DRAG_IDLE_MS)
    }

    const onDragEnter = (e: DragEvent) => {
      e.preventDefault()
      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      keepOpen(e)
    }

    const onDragOver = (e: DragEvent) => {
      e.preventDefault()
      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      keepOpen(e)
    }

    const onDragLeave = (e: DragEvent) => {
      e.preventDefault()
      const x = e.clientX ?? 0
      const y = e.clientY ?? 0
      const outside = x <= 0 || y <= 0 || x >= window.innerWidth || y >= window.innerHeight
      if (outside) close()
    }

    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      close()

      const target = (e.target as Element | null) ?? null
      if (isExcludedTarget(target)) return

      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      const files = Array.from(e.dataTransfer.files ?? []).filter(isAcceptedFile)
      if (files.length === 0) return

      if (isEnrichmentPanelOpen() && files.length > 0 && files.every(isMediaFile)) {
        window.dispatchEvent(new CustomEvent(ENRICHMENT_MEDIA_DROP_EVENT, { detail: { files } }))
        return
      }

      onDropFiles(files)
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }

    window.addEventListener('dragenter', onDragEnter)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('dragleave', onDragLeave)
    window.addEventListener('drop', onDrop)
    window.addEventListener('keydown', onKeyDown)

    return () => {
      window.removeEventListener('dragenter', onDragEnter)
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('dragleave', onDragLeave)
      window.removeEventListener('drop', onDrop)
      window.removeEventListener('keydown', onKeyDown)
      if (idleTimer.current) clearTimeout(idleTimer.current)
    }
  }, [disabled, onDropFiles])

  if (disabled || !active || excluded) return null

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-background/85 backdrop-blur-xs p-6 pointer-events-none select-none animate-in fade-in duration-150"
      data-testid="global-drop-veil"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-primary bg-card px-10 py-8 shadow-2xl">
        <Upload className="size-10 text-primary" aria-hidden />
        <p className="text-lg font-semibold text-foreground">Rilascia per importare</p>
      </div>
    </div>
  )
}
