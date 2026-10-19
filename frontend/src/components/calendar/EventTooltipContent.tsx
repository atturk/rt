import type { CalendarEventView } from '@/api/calendar'
import { Tooltip } from '@/components/ui/tooltip'
import { StatusIcon } from './StatusIcon'
import { STATUS_LABELS } from './calendarUtils'

export function EventTooltipContent({ event, editing = false }: { event: CalendarEventView; editing?: boolean }) {
  const status = event.lesson
    ? event.lesson.units_total > 0
      ? `Seguita · ${event.lesson.units_learned}/${event.lesson.units_total} unità apprese`
      : 'Seguita · in rielaborazione'
    : STATUS_LABELS[event.status] ?? 'Da seguire'
  return <div className="space-y-0.5">
    {editing && <div className="mb-1">Modifica quest'ora</div>}
    <div className="font-semibold">{event.materia}</div>
    <div><span className="font-mono">{event.start_time}–{event.end_time}</span>{event.docente && ` · ${event.docente}`}</div>
    <div>{status}{event.is_modified && <><span className="mx-1 inline-block size-1 rounded-full bg-study-learning" aria-hidden />Solo questa settimana</>}</div>
    {event.note?.trim() && <div className="mt-1 border-t border-background/20 pt-1 whitespace-pre-line line-clamp-4">{event.note}</div>}
  </div>
}

export function EventStatus({ event, className }: { event: CalendarEventView; className: string }) {
  const icon = <><StatusIcon event={event} />{event.note?.trim() && <span className="absolute -right-0.5 -top-0.5 size-1 rounded-full bg-muted-foreground" aria-hidden />}</>
  if (!event.note?.trim()) return <span className={className}>{icon}</span>
  return <Tooltip content={<span className="whitespace-pre-line line-clamp-6">{event.note}</span>} delay={0} side="top" describe={false}>
    {trigger => <span {...trigger} className={className} data-testid={`calendar-note-${event.key}`}>{icon}</span>}
  </Tooltip>
}
