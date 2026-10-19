import type { CalendarDayView, CalendarEventView } from '@/api/calendar'
import { Tooltip } from '@/components/ui/tooltip'
import { getSubjectColor } from './subjectColor'

import { EventStatus, EventTooltipContent } from './EventTooltipContent'
import { getEventTooltip } from './calendarUtils'
import type { PopupAnchor } from './CalendarPopups'


export function CalendarDayList({
  days,
  selectedDayIndex,
  onSelectDayIndex,
  onOpenEvent,
}: {
  days: CalendarDayView[]
  selectedDayIndex: number
  onSelectDayIndex: (index: number) => void
  onOpenEvent: (event: CalendarEventView, anchor: PopupAnchor) => void
}) {
  const currentDay = days[selectedDayIndex] || days[0]

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Striscia dei giorni con pallini delle materie */}
      <div data-testid="calendar-day-strip" className="flex gap-1.5 border-b border-border bg-background px-3 py-2">
        {days.map((day, idx) => {
          const isSelected = idx === selectedDayIndex
          return (
            <button
              key={day.date}
              type="button"
              className={`flex flex-1 flex-col items-center rounded-xl py-1 text-xs transition-colors ${
                isSelected
                  ? 'bg-primary text-primary-foreground font-semibold'
                  : 'text-muted-foreground hover:bg-muted'
              }`}
              onClick={() => onSelectDayIndex(idx)}
            >
              <span>{day.day_name}</span>
              <span className="font-mono text-sm font-semibold">{day.day_number}</span>
              {/* Pallini colorati delle materie */}
              <div className="flex h-1.5 gap-0.5 pt-0.5">
                {(day.events ?? []).slice(0, 5).map((ev) => (
                  <span
                    key={ev.key}
                    style={{ backgroundColor: getSubjectColor(ev.materia) }}
                    className="size-1 rounded-full"
                    aria-hidden
                  />
                ))}
              </div>
            </button>
          )
        })}
      </div>

      {/* Elenco ore del giorno selezionato */}
      <div className="flex-1 overflow-auto p-3">
        {currentDay && (currentDay.events ?? []).length > 0 ? (
          <div className="flex flex-col gap-2.5">
            {(currentDay.events ?? []).map((ev) => {
              const color = getSubjectColor(ev.materia)

              const tooltip = getEventTooltip(ev)

              return (
                <div key={ev.key} className="grid grid-cols-[48px_1fr] items-start gap-2.5">
                  <div className="font-mono text-xs leading-tight text-muted-foreground pt-1.5">
                    {ev.start_time}
                    <br />
                    {ev.end_time}
                  </div>

                  <Tooltip content={<EventTooltipContent event={ev} />} side="top">
                    {(trigger) => (
                      <button
                        type="button"
                        data-testid={`calendar-mobile-event-${ev.key}`}
                        style={{
                          backgroundColor: `color-mix(in oklch, ${color} var(--tint, 12%), var(--bg))`,
                          boxShadow: `inset 3px 0 0 ${color}`,
                        }}
                        className={`relative flex min-h-[56px] flex-col justify-start rounded-lg p-2.5 text-left text-xs ${
                          ev.status === 'annullata' ? 'line-through opacity-60' : ''
                        }`}
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect()
                          onOpenEvent(ev, {
                            x: rect.left,
                            y: rect.top,
                            width: rect.width,
                            height: rect.height,
                          })
                        }}
                        aria-label={tooltip.replace(/\n/g, ', ')}
                        {...trigger}
                      >
                        <span
                          className="font-semibold tracking-wide"
                          style={{ color }}
                        >
                          {ev.materia.toUpperCase()}
                        </span>
                        {ev.docente && (
                          <span className="text-[11px] text-muted-foreground">
                            {ev.docente}
                          </span>
                        )}

                        <EventStatus event={ev} className="absolute bottom-2 right-2.5" />

                        {ev.is_modified && (
                          <span
                            className="absolute right-2 top-2 size-1.5 rounded-full bg-study-learning"
                            title="Solo questa settimana"
                          />
                        )}
                      </button>
                    )}
                  </Tooltip>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="flex h-32 items-center justify-center text-xs text-muted-foreground">
            Nessuna lezione in programma per questo giorno.
          </div>
        )}
      </div>
    </div>
  )
}
