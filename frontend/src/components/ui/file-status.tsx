import { useEffect, useState } from 'react'
import { LoaderCircle, X } from 'lucide-react'
import { Button } from './button'
import { clearFileStatus, useFileStatus } from '@/lib/fileStatus'
import { cn } from '@/lib/utils'

/** Componente montato una volta sola nel Layout principale per mostrare lo stato del salvataggio. */
export function FileStatusBar() {
  const status = useFileStatus()
  const [showFilesFor, setShowFilesFor] = useState<string | null>(null)
  const statusKey = status.kind === 'ready' ? (status.filename ? `${status.label}:${status.filename}` : status.label) : ''
  const showFiles = Boolean(statusKey && showFilesFor === statusKey)

  useEffect(() => {
    if (status.kind !== 'busy' && status.kind !== 'ready') return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (status.kind === 'busy') {
          status.onCancel?.()
          clearFileStatus()
        } else if (status.kind === 'ready') {
          void status.onCancel?.()
          clearFileStatus()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [status])

  if (status.kind === 'idle') return null

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="file-status-bar"
      className={cn(
        'fixed bottom-4 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-3 rounded-lg border bg-card px-4 py-2.5 shadow-panel text-body transition-all max-md:bottom-[calc(76px+env(safe-area-inset-bottom))]',
        status.kind === 'error' && 'border-destructive bg-destructive/10 text-destructive',
      )}
    >
      {status.kind === 'busy' && (
        <>
          <LoaderCircle className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
          <span className="text-sm font-medium">{status.message}</span>
          <button
            type="button"
            aria-label="Annulla"
            onClick={() => {
              status.onCancel?.()
              clearFileStatus()
            }}
            className="rounded p-1 text-muted-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden />
          </button>
        </>
      )}

      {status.kind === 'ready' && (
        <>
          <div className="relative flex items-center gap-1.5">
            <span className="text-sm font-medium">
              {status.filename ? `${status.label}: ${status.filename}` : `${status.label}${status.skippedMessage ? ` ${status.skippedMessage}` : ''}`}
            </span>
            {status.files && status.files.length > 0 && (
              <button
                type="button"
                aria-expanded={showFiles}
                onClick={() => setShowFilesFor(showFiles ? null : statusKey)}
                className="text-xs text-muted-foreground hover:text-foreground underline ml-1 cursor-pointer"
              >
                {showFiles ? 'Nascondi elenco' : 'Elenco'}
              </button>
            )}
            {showFiles && status.files && status.files.length > 0 && (
              <div
                className="absolute bottom-full left-0 mb-2 w-72 max-h-48 overflow-y-auto rounded-md border bg-card p-2 shadow-panel text-xs text-foreground z-50"
                data-testid="file-status-list"
              >
                <ul className="space-y-1">
                  {status.files.map((f) => (
                    <li key={f.name} className="truncate" title={f.name}>
                      {f.name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              onClick={() => void status.onSave()}
            >
              Salva
            </Button>
            {status.canShare && status.onShare && (
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    if (status.file && status.onShare!.length === 1) {
                      await (status.onShare as (f: File) => Promise<void>)(status.file)
                    } else {
                      await (status.onShare as () => Promise<void>)()
                    }
                  } catch (err: unknown) {
                    const error = err as { name?: string; message?: string }
                    if (error?.name === 'AbortError') {
                      return
                    }
                    clearFileStatus()
                  }
                }}
              >
                Condividi
              </Button>
            )}
            <button
              type="button"
              aria-label="Annulla"
              onClick={() => {
                void status.onCancel?.()
                clearFileStatus()
              }}
              className="rounded p-1 text-muted-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>
        </>
      )}

      {status.kind === 'done' && (
        <span className="text-sm font-medium">
          {status.label}: {status.filename}
        </span>
      )}

      {status.kind === 'error' && (
        <>
          <span className="text-sm font-medium">{status.message}</span>
          <button
            type="button"
            aria-label="Chiudi"
            onClick={clearFileStatus}
            className="rounded p-1 text-destructive hover:bg-destructive/20 focus-visible:outline-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden />
          </button>
        </>
      )}
    </div>
  )
}
