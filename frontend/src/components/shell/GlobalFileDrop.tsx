import { useEffect, useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { hasAcceptedDrag, isAcceptedFile, isExcludedTarget } from './globalFileDropUtils'

export function GlobalFileDrop({
  disabled,
  onDropFiles,
}: {
  disabled?: boolean
  onDropFiles: (files: File[]) => void
}) {
  const [active, setActive] = useState(false)
  const [excluded, setExcluded] = useState(false)
  const dragCounter = useRef(0)

  useEffect(() => {
    if (disabled) return

    const onDragEnter = (e: DragEvent) => {
      e.preventDefault()
      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      dragCounter.current++
      setActive(true)
      const target = (e.target as Element | null) ?? null
      setExcluded(isExcludedTarget(target))
    }

    const onDragOver = (e: DragEvent) => {
      e.preventDefault()
      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      const target = (e.target as Element | null) ?? null
      setExcluded(isExcludedTarget(target))
    }

    const onDragLeave = (e: DragEvent) => {
      e.preventDefault()
      dragCounter.current--
      if (
        dragCounter.current <= 0 ||
        e.relatedTarget === null ||
        (e.clientX === 0 && e.clientY === 0)
      ) {
        dragCounter.current = 0
        setActive(false)
        setExcluded(false)
      }
    }

    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      dragCounter.current = 0
      setActive(false)
      setExcluded(false)

      const target = (e.target as Element | null) ?? null
      if (isExcludedTarget(target)) return

      if (!e.dataTransfer || !hasAcceptedDrag(e.dataTransfer)) return
      const files = Array.from(e.dataTransfer.files ?? [])
      if (files.length === 0 || !files.some(isAcceptedFile)) return

      onDropFiles(files)
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        dragCounter.current = 0
        setActive(false)
        setExcluded(false)
      }
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
