import { iconLines, type SubjectIconSpec } from '@/lib/subjectIcon'
import { cn } from '@/lib/utils'

/** Lato del viewBox: l'icona è size-9 (36 px), quindi un'unità SVG = un pixel. */
const BOX = 36
/** Larghezza massima di una riga di testo (margine di 3 px per lato). */
const MAX_WIDTH = 30
/** Larghezza media di un glifo in grassetto, in em: stima per decidere se stringere la riga. */
const GLYPH_EM = 0.64

const FONT_SIZE: Record<SubjectIconSpec['layout'], number> = { single: 22, row: 18, stack: 17 }

/**
 * Icona quadrata della materia: iniziali su sfondo pastello (vedi lib/subjectIcon.ts), in SVG
 * così le lettere restano grandi: una riga che non ci sta si stringe (textLength) invece di
 * rimpicciolire il carattere. Decorativa: il nome della materia sta nel pulsante che la contiene.
 */
export function SubjectIcon({ icon, className }: { icon: SubjectIconSpec; className?: string }) {
  const lines = iconLines(icon)
  const size = FONT_SIZE[icon.layout]
  const lineHeight = size * 0.98
  const top = BOX / 2 - (lineHeight * (lines.length - 1)) / 2
  return (
    <svg
      aria-hidden
      data-testid="subject-icon"
      data-initials={icon.initials.join('')}
      data-layout={icon.layout}
      viewBox={`0 0 ${BOX} ${BOX}`}
      className={cn('size-9 shrink-0 select-none rounded-lg', className)}
      style={{ backgroundColor: icon.color.bg, color: icon.color.fg }}
    >
      {lines.map((line, i) => {
        const squeeze = line.length * size * GLYPH_EM > MAX_WIDTH
        return (
          <text
            key={i}
            x={BOX / 2}
            y={top + i * lineHeight}
            textAnchor="middle"
            dominantBaseline="central"
            fill="currentColor"
            fontSize={size}
            fontWeight={800}
            letterSpacing={squeeze ? '-0.02em' : undefined}
            textLength={squeeze ? MAX_WIDTH : undefined}
            lengthAdjust={squeeze ? 'spacingAndGlyphs' : undefined}
          >
            {line}
          </text>
        )
      })}
    </svg>
  )
}
