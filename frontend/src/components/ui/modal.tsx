import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'

import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'

/**
 * Popup centrale del design 4.2 (Info, Nuova lezione, conferme): sfondo schiarito, X in alto a
 * destra, chiusura con Esc e con un clic fuori. Elemento <dialog> nativo: il focus resta dentro
 * finché è aperto e torna dov'era alla chiusura.
 */
export function Modal({ open, onClose, title, children, className, testId, compact = false }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  className?: string
  testId?: string
  /** Margini stretti (popup Info, 16×18 px nel design). */
  compact?: boolean
}) {
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
      data-testid={testId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      // Il clic sullo sfondo arriva al <dialog> stesso: il contenuto sta tutto nel div interno.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className={cn(
        'm-auto max-h-[calc(100dvh-48px)] w-[min(380px,calc(100vw-32px))] overflow-auto rounded-lg border bg-card p-0 text-foreground shadow-panel',
        // Lo sfondo lascia libera la barra a sinistra (design 00/01c).
        'backdrop:bg-overlay backdrop:backdrop-blur-[3px] md:backdrop:left-(--rail-width)',
        className,
      )}
    >
      {open && (
        <div className={compact ? 'px-[18px] py-4' : 'p-6 max-md:p-5'}>
          <div className="flex items-center gap-2">
            <h2 id={titleId} className="min-w-0 flex-1 text-[15px] font-semibold">
              {title}
            </h2>
            <IconButton label="Chiudi" icon={X} onClick={onClose} className="-my-2 -mr-2" />
          </div>
          {children}
        </div>
      )}
    </dialog>
  )
}
