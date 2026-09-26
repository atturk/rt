import { Badge } from '@/components/ui/badge'
import { PHASE_LABELS, PHASE_ORDER, phaseTone } from '@/lib/format'

export function PhaseBadges({ phases }: { phases: Record<string, string> }) {
  const names = [...PHASE_ORDER.filter((p) => p in phases), ...Object.keys(phases).filter((p) => !PHASE_ORDER.includes(p))]
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Stato delle fasi">
      {names.map((name) => (
        <li key={name}>
          <Badge tone={phaseTone(phases[name])} title={phases[name]} data-phase={name} data-status={phases[name]}>
            <span className="size-1.5 rounded-full bg-current opacity-70" aria-hidden />
            {PHASE_LABELS[name] ?? name}
          </Badge>
        </li>
      ))}
    </ul>
  )
}
