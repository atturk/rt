import { useEffect, useId, useRef, useState } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { BackupEvent } from '@/types/backup.d.ts'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toLocaleString('it-IT', { maximumFractionDigits: 1 })} KB`
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toLocaleString('it-IT', { maximumFractionDigits: 1 })} MB`
  }
  return `${(bytes / (1024 * 1024 * 1024)).toLocaleString('it-IT', { maximumFractionDigits: 1 })} GB`
}

type DialogState =
  | {
      kind: 'in_corso'
      tipo: 'backup' | 'copia'
      fase?: 'database' | 'media' | 'config' | 'copia'
      fatto?: number
      totale?: number
    }
  | {
      kind: 'finito_backup'
      percorso: string
      riepilogo: string[]
      avvisoChiave?: string
    }
  | {
      kind: 'finito_copia'
      percorso: string
    }
  | {
      kind: 'errore'
      messaggio: string
    }

export function BackupDialog() {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<DialogState | null>(null)
  const [savingCopy, setSavingCopy] = useState(false)
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const handler = (evento: BackupEvent) => {
      if ('inizio' in evento && evento.inizio) {
        setOpen(true)
        setState({ kind: 'in_corso', tipo: evento.tipo ?? 'backup' })
      } else if ('fase' in evento) {
        setOpen(true)
        setState({
          kind: 'in_corso',
          tipo: evento.tipo ?? (evento.fase === 'copia' ? 'copia' : 'backup'),
          fase: evento.fase,
          fatto: evento.fatto,
          totale: evento.totale,
        })
      } else if ('fine' in evento && evento.fine) {
        setOpen(true)
        if (evento.tipo === 'copia') {
          setState({ kind: 'finito_copia', percorso: evento.percorso })
        } else {
          setState({
            kind: 'finito_backup',
            percorso: evento.percorso,
            riepilogo: evento.riepilogo ?? [],
            avvisoChiave: evento.avviso_chiave,
          })
        }
      } else if ('errore' in evento) {
        setOpen(true)
        setState({ kind: 'errore', messaggio: evento.errore })
      }
    }

    window.__rtBackup = handler
    return () => {
      if (window.__rtBackup === handler) {
        delete window.__rtBackup
      }
    }
  }, [])

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

  if (!open || !state) return null

  const isInProgress = state.kind === 'in_corso'

  let percent = 0
  let phaseText = ''
  if (state.kind === 'in_corso') {
    if (state.tipo === 'copia') {
      const fatto = state.fatto ?? 0
      const totale = state.totale ?? 0
      percent = totale > 0 ? Math.min(100, Math.round((fatto / totale) * 100)) : 0
      phaseText = totale > 0 ? `Copia ${formatBytes(fatto)} di ${formatBytes(totale)}` : 'Preparazione della copia…'
    } else {
      if (state.fase === 'database') {
        percent = state.fatto === 1 ? 5 : 0
        phaseText = 'Database'
      } else if (state.fase === 'media') {
        const fatto = state.fatto ?? 0
        const totale = state.totale ?? 0
        percent = 5 + (totale > 0 ? Math.round((fatto / totale) * 90) : 90)
        phaseText = `Media ${fatto} di ${totale}`
      } else if (state.fase === 'config') {
        percent = 100
        phaseText = 'Configurazione'
      } else {
        percent = 0
        phaseText = 'Avvio del backup…'
      }
    }
  }

  const handleSalvaCopia = async () => {
    if (state.kind !== 'finito_backup') return
    if (!window.pywebview?.api?.salva_copia_backup) return
    setSavingCopy(true)
    try {
      const res = await window.pywebview.api.salva_copia_backup(state.percorso)
      if (res?.avviato) {
        setState({ kind: 'in_corso', tipo: 'copia' })
      } else if (res?.errore) {
        setState({ kind: 'errore', messaggio: res.errore })
      }
    } catch (exc) {
      setState({ kind: 'errore', messaggio: String(exc) })
    } finally {
      setSavingCopy(false)
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      data-testid="backup-dialog"
      onCancel={(e) => {
        e.preventDefault()
        if (!isInProgress) setOpen(false)
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !isInProgress) setOpen(false)
      }}
      className={cn(
        'm-auto max-h-[calc(100dvh-48px)] w-[min(480px,calc(100vw-32px))] overflow-auto rounded-lg border bg-card p-0 text-foreground shadow-panel',
        'backdrop:bg-overlay backdrop:backdrop-blur-[3px] md:backdrop:left-(--rail-width)'
      )}
    >
      <div className="p-6 max-md:p-5 flex flex-col gap-4">
        {state.kind === 'in_corso' && (
          <>
            <h2 id={titleId} className="text-[15px] font-semibold">
              {state.tipo === 'copia' ? 'Salvo una copia…' : 'Backup in corso…'}
            </h2>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{phaseText}</span>
                <span className="font-mono text-xs font-medium">{percent}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  role="progressbar"
                  aria-valuenow={percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-full bg-primary transition-all duration-200"
                  style={{ width: `${percent}%` }}
                />
              </div>
            </div>
          </>
        )}

        {state.kind === 'finito_backup' && (
          <>
            <h2 id={titleId} className="text-[15px] font-semibold">
              Backup completo
            </h2>
            <div className="flex flex-col gap-3">
              <div className="space-y-1.5 text-sm">
                {state.riepilogo.map((line, i) => (
                  <div
                    key={i}
                    className={line.includes(state.percorso) ? 'font-mono text-xs break-all' : ''}
                  >
                    {line}
                  </div>
                ))}
              </div>
              {state.avvisoChiave && (
                <Alert tone="warning" className="text-xs">
                  {state.avvisoChiave}
                </Alert>
              )}
              <p className="text-xs text-muted-foreground">
                Per sicurezza tieni anche una copia su un altro disco o nel cloud.
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setOpen(false)}>
                Chiudi
              </Button>
              <Button onClick={handleSalvaCopia} disabled={savingCopy}>
                {savingCopy ? 'Salvo…' : 'Salva una copia…'}
              </Button>
            </div>
          </>
        )}

        {state.kind === 'finito_copia' && (
          <>
            <h2 id={titleId} className="text-[15px] font-semibold">
              Copia salvata
            </h2>
            <div className="flex flex-col gap-2 text-sm">
              <p>
                Copia salvata in <span className="font-mono text-xs break-all">{state.percorso}</span>
              </p>
              <p className="text-xs text-muted-foreground">
                Si ripristina con <code className="font-mono">rt restore {state.percorso}</code>
              </p>
            </div>
            <div className="flex justify-end pt-2">
              <Button onClick={() => setOpen(false)}>Chiudi</Button>
            </div>
          </>
        )}

        {state.kind === 'errore' && (
          <>
            <h2 id={titleId} className="text-[15px] font-semibold text-danger">
              Errore
            </h2>
            <Alert tone="danger" className="text-sm">
              {state.messaggio}
            </Alert>
            <div className="flex justify-end pt-2">
              <Button onClick={() => setOpen(false)}>Chiudi</Button>
            </div>
          </>
        )}
      </div>
    </dialog>
  )
}
