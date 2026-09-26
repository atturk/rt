import type { SubjectIconSpec } from '@/lib/subjectIcon'
import { cn } from '@/lib/utils'

const LAYOUT_CLASS: Record<SubjectIconSpec['layout'], string> = {
  single: 'flex items-center justify-center text-base',
  row: 'flex items-center justify-center gap-px text-sm',
  // due sopra e una centrata sotto: la terza occupa tutta la seconda riga
  triangle: 'grid grid-cols-2 place-items-center content-center gap-x-px text-[11px] [&>:nth-child(3)]:col-span-2',
  grid: 'grid grid-cols-2 place-items-center content-center gap-x-px text-[11px]',
}

/** Icona quadrata della materia: iniziali su sfondo pastello (vedi lib/subjectIcon.ts). Decorativa:
 * il nome della materia sta nel pulsante che la contiene. */
export function SubjectIcon({ icon, className }: { icon: SubjectIconSpec; className?: string }) {
  return (
    <span
      aria-hidden
      data-testid="subject-icon"
      data-initials={icon.initials.join('')}
      data-layout={icon.layout}
      className={cn('size-9 shrink-0 select-none rounded-lg font-bold leading-none', LAYOUT_CLASS[icon.layout], className)}
      style={{ backgroundColor: icon.color.bg, color: icon.color.fg }}
    >
      {icon.initials.map((letter, i) => (
        <span key={i} className="leading-[1.1]">
          {letter}
        </span>
      ))}
    </span>
  )
}
