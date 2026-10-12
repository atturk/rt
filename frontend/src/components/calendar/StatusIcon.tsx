import { AlertCircle, Ban, Check, Clock, Mic, SkipForward } from 'lucide-react'
import type { CalendarEventView } from '@/api/calendar'

export function StatusIcon({ event }: { event: CalendarEventView }) {
  if (event.lesson) {
    if (event.lesson.units_total > 0) {
      const r = 6
      const c = 2 * Math.PI * r
      const learned = event.lesson.units_learned
      const total = event.lesson.units_total
      const f = total > 0 ? Math.min(1, learned / total) : 0
      return (
        <svg className="size-[15px]" viewBox="0 0 16 16" aria-hidden>
          <circle cx="8" cy="8" r={r} fill="none" stroke="var(--study-track)" strokeWidth="2.4" />
          <circle
            cx="8"
            cy="8"
            r={r}
            fill="none"
            stroke={f >= 1 ? 'var(--study-learned)' : 'var(--study-learning)'}
            strokeWidth="2.4"
            strokeDasharray={`${c * f} ${c}`}
            transform="rotate(-90 8 8)"
            strokeLinecap="round"
          />
        </svg>
      )
    }
    return <Mic className="size-[15px] text-muted-foreground" aria-hidden />
  }

  switch (event.status) {
    case 'seguita':
      return <Check className="size-[15px] text-study-learned" aria-hidden />
    case 'nonseguita':
      return <AlertCircle className="size-[15px] text-danger" aria-hidden />
    case 'saltare':
      return <SkipForward className="size-[15px] text-muted-foreground" aria-hidden />
    case 'annullata':
      return <Ban className="size-[15px] text-muted-foreground" aria-hidden />
    case 'seguire':
    default:
      return <Clock className="size-[15px] text-muted-foreground" aria-hidden />
  }
}
