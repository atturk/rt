import type { CalendarYearWeek } from '@/api/calendar'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { getSubjectColor } from './subjectColor'
import { shiftWeekDate, weekMonth, weekTitle } from './weekRange'

export function CalendarYearView({ weeks, selected, onSelect, onOpen }: {
  weeks: CalendarYearWeek[]; selected: string[]; onSelect: (monday: string) => void; onOpen: (monday: string) => void
}) {
  const months = [...new Set(weeks.map(week => weekMonth(week.start_date)))]
  const allEvents = weeks.flatMap(week => week.days.flatMap(day => day.events))
  const min = allEvents.length ? Math.min(...allEvents.map(event => event.start_hour)) : 8
  const max = allEvents.length ? Math.max(...allEvents.map(event => event.end_hour)) : 19
  const span = Math.max(1, max - min)
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const fingerprint = (week?: CalendarYearWeek) => week ? JSON.stringify(week.days.flatMap((day, i) => day.events.map(e => [i, e.start_hour, e.end_hour, e.materia]))) : '[]'
  return <div className="grid w-full content-start gap-5 p-4 [grid-template-columns:repeat(auto-fill,minmax(290px,1fr))]" data-testid="calendar-year-view">
    {months.map(month => <section key={month} aria-label={month}>
      <h2 className="mb-2 text-sm font-semibold capitalize">{new Date(`${month}-15T00:00:00Z`).toLocaleDateString('it-IT', { month: 'long', year: 'numeric', timeZone: 'UTC' })}</h2>
      <div className="flex flex-col gap-1">
        {weeks.filter(week => weekMonth(week.start_date) === month).map(week => {
          const index = weeks.indexOf(week)
          const changed = index > 0 && fingerprint(weeks[index - 1]) !== fingerprint(week)
          const current = week.start_date <= today && shiftWeekDate(week.start_date, 7) > today
          const past = shiftWeekDate(week.start_date, 7) <= today
          const hours = week.days.flatMap(day => day.events).reduce((n, e) => n + (e.status === 'annullata' ? 0 : e.end_hour - e.start_hour), 0)
          const title = weekTitle(week.start_date, hours, changed)
          return <Tooltip key={week.start_date} content={title} describe={false}>{trigger => <button {...trigger} type="button" aria-label={title} aria-pressed={selected.includes(week.start_date)} data-week={week.start_date}
            data-changed={changed} data-current={current} className={cn('flex w-full items-center gap-2 rounded border border-transparent p-1', current && 'border-foreground', selected.includes(week.start_date) && 'ring-2 ring-success')}
            style={changed ? { boxShadow: 'inset 3px 0 0 var(--study-learning)' } : undefined}
            onClick={() => onSelect(week.start_date)} onDoubleClick={() => onOpen(week.start_date)}
            onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); onOpen(week.start_date) } }}>
            <span className="w-5 shrink-0 font-mono text-[10px] text-muted-foreground">{week.week_number}</span>
            <span className="flex flex-1 gap-1">
              {week.days.map(day => <span key={day.date} className="relative block h-[14px] flex-1 overflow-hidden rounded-xs bg-muted/40" aria-hidden>
                {day.events.map((event, i) => <span key={i} className="absolute inset-y-0" style={{
                  left: `${(event.start_hour - min) / span * 100}%`, width: `${(event.end_hour - event.start_hour) / span * 100}%`,
                  backgroundColor: event.status === 'annullata' ? 'var(--muted-foreground)' : past ? getSubjectColor(event.materia) : `color-mix(in srgb, ${getSubjectColor(event.materia)} 42%, white)`,
                  ...(event.status === 'nonseguita' ? { boxShadow: 'inset 0 0 0 1.5px var(--danger)' } : {}),
                }} />)}
              </span>)}
            </span>
          </button>}</Tooltip>
        })}
      </div>
    </section>)}
  </div>
}
