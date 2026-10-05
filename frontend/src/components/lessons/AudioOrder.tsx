import { GripVertical, X } from 'lucide-react'
import { useState, type DragEvent, type KeyboardEvent } from 'react'

import { IconButton } from '@/components/ui/icon-button'
import { formatBytes } from '@/lib/jobs'
import { moveItem } from '@/lib/order'
import { cn } from '@/lib/utils'

/** Tipo del trascinamento interno: una riga della lista, non file nuovi dal Finder. */
const DRAG_TYPE = 'application/x-rt-audio-index'

/**
 * Ordine degli audio della lezione: è quello in cui i file diventano un'unica registrazione.
 * Si riordina trascinando una riga o, da tastiera, con le frecce su e giù sulla maniglia.
 */
export function AudioOrder({ files, onChange, disabled }: { files: File[]; onChange: (files: File[]) => void; disabled?: boolean }) {
  const [dragged, setDragged] = useState<number | null>(null)
  const [over, setOver] = useState<number | null>(null)

  function drop(event: DragEvent, index: number) {
    if (!event.dataTransfer.types.includes(DRAG_TYPE)) return
    event.preventDefault()
    event.stopPropagation()
    const from = Number(event.dataTransfer.getData(DRAG_TYPE))
    if (Number.isInteger(from)) onChange(moveItem(files, from, index))
    setDragged(null)
    setOver(null)
  }

  function keyMove(event: KeyboardEvent, index: number) {
    const to = event.key === 'ArrowUp' ? index - 1 : event.key === 'ArrowDown' ? index + 1 : null
    if (to === null || to < 0 || to >= files.length) return
    event.preventDefault()
    onChange(moveItem(files, index, to))
    // la maniglia segue il file spostato
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-audio-handle="${to}"]`)?.focus())
  }

  // Chiave stabile durante il riordino; lo stesso file scelto due volte ha la sua occorrenza.
  const seen = new Map<string, number>()
  const keys = files.map((file) => {
    const base = `${file.name}-${file.lastModified}-${file.size}`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    return `${base}-${n}`
  })

  return (
    <ol aria-label="Ordine degli audio" className="my-4 space-y-1" data-testid="audio-order">
      {files.map((file, index) => (
        <li
          key={keys[index]}
          draggable={!disabled}
          data-testid="audio-order-item"
          onDragStart={(event) => {
            event.dataTransfer.setData(DRAG_TYPE, String(index))
            event.dataTransfer.effectAllowed = 'move'
            setDragged(index)
          }}
          onDragOver={(event) => {
            if (!event.dataTransfer.types.includes(DRAG_TYPE)) return
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
            setOver(index)
          }}
          onDragLeave={() => setOver((current) => (current === index ? null : current))}
          onDrop={(event) => drop(event, index)}
          onDragEnd={() => { setDragged(null); setOver(null) }}
          className={cn(
            'flex items-center gap-2 rounded-md border bg-card py-1 pl-1.5 pr-1 text-meta',
            !disabled && 'cursor-grab active:cursor-grabbing',
            dragged === index && 'opacity-50',
            over === index && dragged !== index && 'border-foreground',
          )}
        >
          <button
            type="button"
            data-audio-handle={index}
            disabled={disabled}
            aria-label={`Riordina ${file.name}: posizione ${index + 1} di ${files.length}, usa le frecce su e giù`}
            title="Trascina per riordinare (o usa le frecce)"
            onKeyDown={(event) => keyMove(event, index)}
            className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
          >
            <GripVertical className="size-4" aria-hidden />
          </button>
          <span className="w-4 shrink-0 text-right text-muted-foreground">{index + 1}</span>
          <span className="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span>
          <span className="shrink-0 text-muted-foreground">{formatBytes(file.size)}</span>
          <IconButton label={`Rimuovi ${file.name}`} icon={X} disabled={disabled} onClick={() => onChange(files.filter((_, i) => i !== index))} />
        </li>
      ))}
    </ol>
  )
}
