import { Tag } from 'lucide-react'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export type StripUnit = { unit_id: string; title: string; included: boolean; unclassified?: boolean }
export function UnitStrip({ units, target, rule, onSelect, classifierEnabled, classifierUpdated, onClassifier }: {
  units: StripUnit[]; target: 'revisore' | 'recaller'; rule: string; onSelect: () => void
  classifierEnabled: boolean; classifierUpdated: boolean; onClassifier?: () => void
}) {
  const label = `Rivedi le etichette · classificatore ${classifierUpdated ? 'aggiornato' : 'da aggiornare'}`
  return <div className="mt-auto flex items-center gap-2 border-t pt-3 text-meta" data-testid={`unit-strip-${target}`}>
    <Tooltip content={rule}>{trigger => <button {...trigger} type="button" aria-label={rule} onClick={onSelect} className="flex min-h-[34px] min-w-0 flex-1 items-center gap-0.5 rounded-md px-1 focus-visible:outline-2 focus-visible:outline-ring" data-testid="unit-strip-ticks">
      {units.map(unit => {
        const state = !unit.included ? 'excluded' : unit.unclassified ? 'unclassified' : 'included'
        const hint = `${unit.unit_id} ${unit.title} · ${!unit.included ? 'esclusa' : unit.unclassified ? `non classificata, va al ${target}` : `va al ${target}`}`
        return <Tooltip key={unit.unit_id} content={hint}>{props => <span {...props} aria-label={hint} data-state={state} className={cn('h-2 min-w-0 flex-1 rounded-xs border border-accent-foreground', state === 'included' && 'bg-accent-foreground', state === 'unclassified' && 'rt-unit-strip-unclassified')} />}</Tooltip>
      })}
    </button>}</Tooltip>
    <span className="shrink-0 tabular-nums" data-testid="unit-strip-count">{units.filter(unit => unit.included).length}/{units.length}</span>
    {classifierEnabled && <IconButton label={label} icon={Tag} onClick={onClassifier ?? onSelect} badge={<span aria-hidden data-testid="classifier-dot" className={cn('absolute right-1 top-1 size-1.5 rounded-full', classifierUpdated ? 'bg-success' : 'bg-warning')} />} />}
  </div>
}
