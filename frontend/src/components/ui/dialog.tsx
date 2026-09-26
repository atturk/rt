import { useEffect, useId, useRef, type ReactNode } from 'react'

import { Button } from './button'

type ConfirmDialogProps = {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  onConfirm: () => void
  onCancel: () => void
}

/** Dialogo modale di conferma (elemento <dialog> nativo: focus intrappolato, Esc chiude). */
export function ConfirmDialog({ open, title, children, confirmLabel, cancelLabel = 'Annulla', onConfirm, onCancel }: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        onCancel()
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border bg-card p-5 text-foreground shadow-lg backdrop:bg-black/40"
    >
      {open && (
        <div className="flex flex-col gap-4">
          <h2 id={titleId} className="text-base font-bold">
            {title}
          </h2>
          <div className="text-sm">{children}</div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={onCancel}>
              {cancelLabel}
            </Button>
            <Button onClick={onConfirm}>{confirmLabel}</Button>
          </div>
        </div>
      )}
    </dialog>
  )
}
