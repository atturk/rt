import { LoaderCircle, X } from 'lucide-react'
import { Button } from './button'
import { saveFile } from '@/lib/fileExport'
import { clearFileStatus, setFileStatus, useFileStatus } from '@/lib/fileStatus'
import { cn } from '@/lib/utils'

/** Componente montato una volta sola nel Layout principale per mostrare lo stato del salvataggio. */
export function FileStatusBar() {
  const status = useFileStatus()

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
        </>
      )}

      {status.kind === 'ready' && (
        <>
          <span className="text-sm font-medium">
            {status.label}: {status.file.name}
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              onClick={() => {
                saveFile(status.file)
                setFileStatus({ kind: 'done', label: status.label, filename: status.file.name })
              }}
            >
              Salva
            </Button>
            {status.isShare && status.onShare && (
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await status.onShare!(status.file)
                    clearFileStatus()
                  } catch (err: unknown) {
                    const error = err as { name?: string; message?: string }
                    if (error?.name === 'AbortError') {
                      clearFileStatus()
                    } else {
                      setFileStatus({ kind: 'error', message: error?.message ?? 'Condivisione non riuscita' })
                    }
                  }
                }}
              >
                Condividi
              </Button>
            )}
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
