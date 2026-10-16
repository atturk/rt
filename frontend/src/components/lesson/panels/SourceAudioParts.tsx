import { useId, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { SourcePartItem } from '@/api/sources'
import { Tooltip } from '@/components/ui/tooltip'
import { formatSourceDuration } from '@/lib/sourcesFormat'

const COLORS = ['bg-primary', 'bg-primary/65', 'bg-primary/35']

/** Nome accorciato al centro: l'orario alla fine del file resta leggibile. */
function PartName({ name }: { name: string }) {
  return <Tooltip content={name}>{(trigger) => (
    <span {...trigger} tabIndex={0} className="flex min-w-0 items-baseline overflow-hidden">
      {name.length > 24 ? <><span className="min-w-0 truncate">{name.slice(0, -16)}</span><span className="shrink-0">{name.slice(-16)}</span></> : <span className="truncate">{name}</span>}
    </span>
  )}</Tooltip>
}

export function SourceAudioParts({ sourceId, parts }: { sourceId: string; parts: SourcePartItem[] }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const weights = parts.map((part) => Math.max(0, part.durata_s ?? 0))
  const knownDuration = weights.some((value) => value > 0)
  const Chevron = open ? ChevronUp : ChevronDown
  return <div className="grid w-full min-w-0 gap-2" data-testid={`source-audio-parts-${sourceId}`}>
    <Tooltip content={open ? 'Nascondi le parti della registrazione' : 'Mostra le parti della registrazione'}>{(trigger) => (
      <button type="button" {...trigger} aria-label={`${parts.length} parti`} aria-expanded={open} aria-controls={id}
        onClick={() => setOpen((value) => !value)} className="inline-flex w-fit items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-meta text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
        {parts.length} parti <Chevron className="size-3" aria-hidden />
      </button>
    )}</Tooltip>
    <div className="flex h-1.5 w-full min-w-0 gap-0.5 overflow-hidden rounded-full" aria-hidden data-testid={`source-parts-bar-${sourceId}`}>
      {parts.map((_, index) => <span key={index} className={COLORS[index % COLORS.length]} style={{ flexGrow: knownDuration ? weights[index] : 1, flexBasis: 0 }} />)}
    </div>
    {open && <div id={id} className="grid w-full min-w-0 gap-1" data-testid={`source-parts-${sourceId}`}>
      {parts.map((part, index) => <div key={index} className="grid min-w-0 grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-2 text-meta">
        <span aria-hidden className={`size-2.5 rounded-sm ${COLORS[index % COLORS.length]}`} />
        <PartName name={part.nome} />
        <span className="whitespace-nowrap text-muted-foreground tabular-nums">{part.durata || formatSourceDuration(part.durata_s)}</span>
      </div>)}
    </div>}
  </div>
}
