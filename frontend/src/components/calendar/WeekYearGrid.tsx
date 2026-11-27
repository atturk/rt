import { Check, ChevronLeft, ChevronRight, Calendar as CalendarIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { CalendarTemplateEntryView } from '@/api/calendar'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { academicYear, academicWeeks, isoWeek, shiftWeekDate, weekMonday, weekMonth, weekOccupancy, weekTitle, type WeekRange } from './weekRange'

export type WeekSelectModifiers = { mod: boolean; shift: boolean }

export function WeekYearGrid({
  currentDate,
  entries,
  selected: selectedSet,
  range,
  first,
  onSelect,
  onWeekSelect,
  onDragStart,
  onDragMove,
  onToday,
}: {
  currentDate: string
  entries: CalendarTemplateEntryView[]
  selected?: ReadonlySet<string>
  range?: WeekRange | null
  first?: string | null
  onSelect?: (week: string) => void
  onWeekSelect?: (week: string, modifiers: WeekSelectModifiers) => void
  onDragStart?: (week: string) => void
  onDragMove?: (startWeek: string, currentWeek: string) => void
  onToday?: () => void
}) {
  const [year, setYear] = useState(() => Math.max(2025, Math.min(2035, academicYear(currentDate))))
  const root = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef<string | null>(null)
  const multiSelect = Boolean(onWeekSelect || onDragStart || onDragMove)

  useEffect(() => {
    function finishDrag() { dragStartRef.current = null }
    window.addEventListener('pointerup', finishDrag)
    window.addEventListener('pointercancel', finishDrag)
    return () => {
      window.removeEventListener('pointerup', finishDrag)
      window.removeEventListener('pointercancel', finishDrag)
    }
  }, [])

  const weeks = academicWeeks(year)
  const months = [...new Set(weeks.map(weekMonth))]
  const values = weeks.map(monday => weekOccupancy(entries, monday))
  const maxHours = Math.max(1, ...values.map(value => value.hours))
  const now = new Date()
  const today = weekMonday(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`)

  return <div ref={root}>
    <div className="mb-2 flex items-center justify-between">
      <IconButton label="Anno precedente" icon={ChevronLeft} disabled={year <= 2025} onClick={() => setYear(year - 1)} />
      <span className="font-mono font-semibold" data-testid="calendar-range-year">{year}/{String(year + 1).slice(-2)}</span>
      {onToday && <IconButton label="Oggi" icon={CalendarIcon} onClick={onToday} />}
      <IconButton label="Anno successivo" icon={ChevronRight} disabled={year >= 2035} onClick={() => setYear(year + 1)} />
    </div>
    <div
      ref={gridRef}
      aria-label={`Settimane del ${year}/${year + 1}`}
      className={cn('flex flex-col divide-y', multiSelect && 'select-none touch-none')}
      onPointerMove={event => {
        if (!multiSelect || !dragStartRef.current) return
        const target = document.elementFromPoint?.(event.clientX, event.clientY)?.closest?.<HTMLElement>('[data-week]')
        const week = target?.dataset.week
        if (week) onDragMove?.(dragStartRef.current, week)
      }}
      onPointerUp={event => {
        if (gridRef.current?.hasPointerCapture?.(event.pointerId)) {
          gridRef.current.releasePointerCapture?.(event.pointerId)
        }
        dragStartRef.current = null
      }}
    >
      {months.map(month => <div key={month} data-month={month} className="grid grid-cols-[3.5rem_repeat(5,minmax(0,1fr))] items-center gap-1 py-1">
        <span className="text-[10px] text-muted-foreground">{new Date(`${month}-15T00:00:00Z`).toLocaleDateString('it-IT', { month: 'short', ...(month.endsWith('-09') || month.endsWith('-01') ? { year: '2-digit' } : {}), timeZone: 'UTC' })}</span>
        {weeks.filter(week => weekMonth(week) === month).map(monday => {
          const index = weeks.indexOf(monday), value = values[index]
          const changed = value.fingerprint !== weekOccupancy(entries, shiftWeekDate(monday, -7)).fingerprint
          const isSelected = selectedSet ? selectedSet.has(monday) : range ? monday >= range.from && monday < range.to : monday === first
          const past = monday < today, current = monday === today
          const title = weekTitle(monday, value.hours, changed)
          return <Tooltip key={monday} content={title} describe={false}>{trigger => <button
            {...trigger}
            type="button"
            aria-label={title}
            aria-pressed={isSelected}
            data-week={monday}
            data-past={past}
            data-current={current}
            data-changed={changed}
            data-occupied={value.hours > 0}
            className={cn(
              'relative flex h-10 min-w-0 flex-col items-center justify-center rounded border font-mono text-[11px]',
              value.hours > 0 && 'occupata',
              past && 'bg-muted text-muted-foreground',
              !past && !value.hours && 'border-dashed',
              isSelected && 'border-success bg-(--acc) text-white',
              current && 'border-2 border-foreground',
            )}
            style={{
              ...(changed ? { boxShadow: 'inset 3px 0 0 var(--study-learning)' } : {}),
              ...(!past && value.hours > 0 && !isSelected ? { backgroundColor: `color-mix(in oklch, var(--study-learned) ${20 + value.hours / maxHours * 35}%, var(--background))` } : {}),
            }}
            onPointerDown={event => {
              trigger.onPointerDown()
              if (!multiSelect || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return
              dragStartRef.current = monday
              gridRef.current?.setPointerCapture?.(event.pointerId)
              onDragStart?.(monday)
            }}
            onPointerEnter={() => {
              if (!multiSelect || !dragStartRef.current) return
              onDragMove?.(dragStartRef.current, monday)
            }}
            onKeyDown={event => {
              trigger.onKeyDown(event)
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (multiSelect) onWeekSelect?.(monday, { mod: event.metaKey || event.ctrlKey, shift: event.shiftKey })
                else onSelect?.(monday)
                return
              }
              const step: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 5, ArrowUp: -5 }
              if (!(event.key in step)) return
              event.preventDefault()
              const target = weeks[Math.max(0, Math.min(weeks.length - 1, index + step[event.key]))]
              root.current?.querySelector<HTMLButtonElement>(`[data-week="${target}"]`)?.focus()
            }}
            onClick={event => {
              if (multiSelect) onWeekSelect?.(monday, { mod: event.metaKey || event.ctrlKey, shift: event.shiftKey })
              else onSelect?.(monday)
            }}
          >
            <span>{isoWeek(monday).number}</span>
            <span className="text-[8px]">{current ? 'oggi' : new Date(`${monday}T00:00:00Z`).toLocaleDateString('it-IT', { day: 'numeric', month: 'short', timeZone: 'UTC' })}</span>
            {past && <Check className="absolute right-0 top-0 size-2" aria-hidden />}
          </button>}</Tooltip>
        })}
      </div>)}
    </div>
  </div>
}
