import { useRef } from 'react'
import { AlertCircle, Ban, Plus, SkipForward, X } from 'lucide-react'
import type { CalendarDayView, CalendarEventView } from '@/api/calendar'
import { Tooltip } from '@/components/ui/tooltip'
import { getSubjectColor } from './subjectColor'
import { StatusIcon } from './StatusIcon'
import { getEventTooltip } from './calendarUtils'
import type { PopupAnchor } from './CalendarPopups'


const T0 = 8.5
const HOURS_COUNT = 10 // 08:30 .. 17:30
const HOUR_HEIGHT = 46

function fmtHour(h: number): string {
  const H = Math.floor(h)
  const m = Math.round((h - H) * 60)
  return `${String(H).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export function CalendarWeekGrid({
  days,
  editing,
  selectedEventKey,
  onOpenEvent,
  onOpenDayMenu,
  onOpenAdd,
  onRemoveEvent,
}: {
  days: CalendarDayView[]
  editing: 'week' | 'tpl' | null
  selectedEventKey: string | null
  onOpenEvent: (event: CalendarEventView, anchor: PopupAnchor) => void
  onOpenDayMenu: (day: CalendarDayView, anchor: PopupAnchor) => void
  onOpenAdd: (day: CalendarDayView, hour: number, anchor: PopupAnchor) => void
  onRemoveEvent: (event: CalendarEventView) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Calcolo linea orario corrente (oggi)
  const now = new Date()
  const nowHour = now.getHours() + now.getMinutes() / 60
  const showNowLine = nowHour >= T0 && nowHour <= T0 + HOURS_COUNT

  return (
    <div
      ref={containerRef}
      className={`grid w-full min-w-[700px] select-none grid-cols-[52px_repeat(5,1fr)] ${
        editing ? 'editing-grid' : ''
      }`}
    >
      {/* Cella d'angolo in alto a sinistra */}
      <div className="sticky top-0 z-10 border-b border-border bg-background h-12" />

      {/* Intestazioni dei giorni */}
      {days.map((day) => (
        <div
          key={day.date}
          className="sticky top-0 z-10 flex h-12 items-center justify-center border-b border-l border-border bg-background"
        >
          <Tooltip content="Segna tutto il giorno" side="bottom">
            {(trigger) => (
              <button
                type="button"
                data-testid={`calendar-day-header-${day.day_name}`}
                className="flex items-baseline gap-1.5 rounded-lg px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect()
                  onOpenDayMenu(day, {
                    x: rect.left,
                    y: rect.bottom,
                    width: rect.width,
                    height: rect.height,
                  })
                }}
                {...trigger}
              >
                <span>{day.day_name}</span>
                <span
                  className={`font-semibold font-mono text-sm ${
                    day.is_today
                      ? 'rounded-full bg-primary px-1.5 text-primary-foreground'
                      : 'text-foreground'
                  }`}
                >
                  {day.day_number}
                </span>
                {day.status && (
                  <span className="text-danger ml-0.5">
                    {day.status === 'saltare' && <SkipForward className="size-3" />}
                    {day.status === 'annullata' && <Ban className="size-3" />}
                    {day.status === 'nonseguita' && <AlertCircle className="size-3" />}
                  </span>
                )}
              </button>
            )}
          </Tooltip>
        </div>
      ))}

      {/* Colonna orari */}
      <div className="pt-2">
        {Array.from({ length: HOURS_COUNT }, (_, i) => T0 + i).map((h) => (
          <div
            key={h}
            style={{ height: `${HOUR_HEIGHT}px` }}
            className="-translate-y-2 pr-2 text-right font-mono text-[11px] text-muted-foreground"
          >
            {fmtHour(h)}
          </div>
        ))}
      </div>

      {/* 5 Colonne dei giorni con blocchi ore */}
      {days.map((day) => {
        // Slot vuoti per aggiunta in modalità modifica
        const emptySlots: number[] = []
        const events = day.events ?? []
        if (editing) {
          for (let t = T0; t < T0 + HOURS_COUNT - 0.5; t += 1.0) {
            // Se non c'è già un evento che copre quest'ora
            const occupied = events.some(
              (e) => t >= e.start_hour && t < e.end_hour,
            )
            if (!occupied) {
              emptySlots.push(t)
            }
          }
        }

        return (
          <div
            key={day.date}
            style={{
              height: `${HOURS_COUNT * HOUR_HEIGHT + 10}px`,
              backgroundImage: `repeating-linear-gradient(to bottom, transparent 0 ${HOUR_HEIGHT - 1}px, var(--border) ${HOUR_HEIGHT - 1}px ${HOUR_HEIGHT}px)`,
            }}
            className="relative mt-2 border-l border-border/50"
          >
            {/* Slot per aggiunta (+) in modalità modifica */}
            {editing &&
              emptySlots.map((h) => (
                <Tooltip key={h} content={`Aggiungi alle ${fmtHour(h)}`} side="top">
                  {(trigger) => (
                    <button
                      type="button"
                      style={{
                        top: `${(h - T0) * HOUR_HEIGHT + 2}px`,
                        height: `${HOUR_HEIGHT - 4}px`,
                      }}
                      className="absolute inset-x-1 flex items-center justify-center rounded-lg border border-dashed border-border text-muted-foreground opacity-0 transition-opacity hover:opacity-100 hover:bg-muted/40"
                      onClick={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect()
                        onOpenAdd(day, h, {
                          x: rect.left,
                          y: rect.top,
                          width: rect.width,
                          height: rect.height,
                        })
                      }}
                      aria-label={`Aggiungi alle ${fmtHour(h)}`}
                      {...trigger}
                    >
                      <Plus className="size-4" />
                    </button>
                  )}
                </Tooltip>
              ))}

            {/* Eventi del giorno */}
            {events.map((ev) => {
              const color = getSubjectColor(ev.materia)

              const top = (ev.start_hour - T0) * HOUR_HEIGHT + 2
              const height = (ev.end_hour - ev.start_hour) * HOUR_HEIGHT - 4
              const isSelected = selectedEventKey === ev.key
              const tooltip = getEventTooltip(ev)

              return (
                <Tooltip key={ev.key} content={tooltip} side="top">
                  {(trigger) => (
                    <button
                      type="button"
                      data-testid={`calendar-event-${ev.key}`}
                      style={{
                        top: `${top}px`,
                        height: `${height}px`,
                        backgroundColor: `color-mix(in oklch, ${color} var(--tint, 12%), var(--bg))`,
                        boxShadow: `inset 3px 0 0 ${color}`,
                      }}
                      className={`group absolute inset-x-1 flex flex-col justify-start gap-0.5 rounded-lg p-2 text-left text-xs transition-colors hover:brightness-95 ${
                        isSelected ? 'ring-2 ring-primary ring-offset-1' : ''
                      } ${
                        ev.status === 'annullata'
                          ? 'bg-muted opacity-60 line-through'
                          : ''
                      }`}
                      onClick={(e) => {
                        if (editing) return
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
                        className="truncate font-semibold tracking-wide"
                        style={{ color }}
                      >
                        {ev.materia.toUpperCase()}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {ev.start_time}–{ev.end_time}
                      </span>

                      {/* Icona di stato in basso a destra */}
                      <span className="absolute bottom-1.5 right-2">
                        <StatusIcon event={ev} />
                      </span>

                      {/* Pallino arancione per modifiche specifiche ("Solo questa settimana") */}
                      {ev.is_modified && !editing && (
                        <span
                          className="absolute right-2 top-2 size-1.5 rounded-full bg-study-learning"
                          title="Solo questa settimana"
                          aria-label="Solo questa settimana"
                        />
                      )}

                      {/* Tasto Rimuovi (×) in modalità modifica */}
                      {editing && (
                        <button
                          type="button"
                          className="absolute right-1 top-1 flex size-5 items-center justify-center rounded bg-background/90 text-muted-foreground shadow-xs hover:text-danger"
                          onClick={(e) => {
                            e.stopPropagation()
                            onRemoveEvent(ev)
                          }}
                          aria-label="Togli quest'ora"
                        >
                          <X className="size-3.5" />
                        </button>
                      )}
                    </button>
                  )}
                </Tooltip>
              )
            })}

            {/* Linea ora corrente (se oggi) */}
            {day.is_today && showNowLine && (
              <div
                style={{ top: `${(nowHour - T0) * HOUR_HEIGHT}px` }}
                className="pointer-events-none absolute inset-x-0 z-20 h-0.5 bg-danger"
              >
                <div className="absolute -left-1 -top-1 size-2.5 rounded-full bg-danger" />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
