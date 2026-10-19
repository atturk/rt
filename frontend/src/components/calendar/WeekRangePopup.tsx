import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import type { CalendarTemplateEntryView } from '@/api/calendar'
import type { PopupAnchor } from './CalendarPopups'
import { computePopupStyle } from './popupPosition'
import { isoWeek, selectWeekRange, shiftWeekDate, weekDateLabel, weekMonday, weekOccupancy, yearWeeks, type WeekRange } from './weekRange'

export function WeekRangePopup({ anchor, currentDate, entries, initial, onClose, onConfirm }: {
  anchor: PopupAnchor; currentDate: string; entries: CalendarTemplateEntryView[]; initial?: WeekRange | null
  onClose: () => void; onConfirm: (range: WeekRange) => void
}) {
  const [year, setYear] = useState(() => Math.max(2025, Math.min(2035, isoWeek(currentDate).year)))
  const [first, setFirst] = useState<string | null>(initial?.from ?? null)
  const [last, setLast] = useState<string | null>(initial ? shiftWeekDate(initial.to, -7) : null)
  const popup = useRef<HTMLDivElement>(null)
  const weeks = yearWeeks(year)
  const occupancy = weeks.map(monday => weekOccupancy(entries, monday))
  const maxHours = Math.max(1, ...occupancy.map(value => value.hours))
  const range = first && last ? selectWeekRange(first, last) : null
  const today = new Date()
  const currentMonday = weekMonday(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`)
  useEffect(() => {
    function key(event: KeyboardEvent) { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }
    function outside(event: PointerEvent) { if (popup.current && !popup.current.contains(event.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    window.addEventListener('pointerdown', outside)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('pointerdown', outside) }
  }, [onClose])
  return <div ref={popup} onKeyDownCapture={event => {
    if (event.key === 'Escape') { event.stopPropagation(); onClose() }
  }} role="dialog" aria-label="Intervallo di settimane" data-testid="calendar-range-popup"
    style={computePopupStyle(anchor, Math.min(350, window.innerWidth - 24))}
    className="rounded-xl border bg-background p-3 text-xs shadow-xl">
    <div className="mb-2 flex items-center justify-between">
      <button type="button" aria-label="Anno precedente" disabled={year === 2025} onClick={() => setYear(year - 1)} className="rounded p-1 hover:bg-muted disabled:opacity-30"><ChevronLeft className="size-4" /></button>
      <span className="font-mono font-semibold" data-testid="calendar-range-year">{year}</span>
      <button type="button" aria-label="Anno successivo" disabled={year === 2035} onClick={() => setYear(year + 1)} className="rounded p-1 hover:bg-muted disabled:opacity-30"><ChevronRight className="size-4" /></button>
    </div>
    <div className="grid grid-cols-13 gap-1" aria-label={`Settimane del ${year}`}>
      {weeks.map((monday, index) => {
        const value = occupancy[index]
        const changed = value.fingerprint !== weekOccupancy(entries, shiftWeekDate(monday, -7)).fingerprint
        const selected = range ? monday >= range.from && monday < range.to : monday === first
        const month = new Date(`${monday}T00:00:00Z`).getUTCMonth()
        const previousMonth = index ? new Date(`${weeks[index - 1]}T00:00:00Z`).getUTCMonth() : -1
        const title = `Settimana ${index + 1} · ${weekDateLabel(monday)}–${weekDateLabel(shiftWeekDate(monday, 4))} · ${value.hours.toLocaleString('it-IT')} ore`
        return <div key={monday} className="min-w-0 text-center">
          <div aria-hidden className="h-3 text-[9px] text-muted-foreground">{month !== previousMonth || index % 13 === 0 ? new Date(`${monday}T00:00:00Z`).toLocaleDateString('it-IT', { month: 'narrow', timeZone: 'UTC' }) : ''}</div>
          <Tooltip content={title} describe={false}>{trigger => <button {...trigger} type="button" aria-label={title} aria-pressed={selected} data-week={monday}
            data-occupied={value.hours > 0} data-changed={changed}
            className={`h-[20px] w-full rounded-sm font-mono text-[10px] ${value.hours > 0 ? 'occupata' : 'bg-muted/40'} ${changed ? 'border-l-2 border-study-learning' : ''} ${monday === currentMonday ? 'ring-1 ring-primary ring-offset-1' : ''} ${selected ? 'outline-2 outline-study-learned outline-offset-1' : ''}`}
            style={value.hours > 0 ? { backgroundColor: `color-mix(in oklch, var(--study-learned) ${20 + value.hours / maxHours * 35}%, var(--background))` } : undefined}
            onClick={() => { if (!first || last) { setFirst(monday); setLast(null) } else setLast(monday) }}>
            {index + 1}
          </button>}</Tooltip>
        </div>
      })}
    </div>
    <div className="my-2 min-h-8 text-muted-foreground" aria-live="polite">
      {range ? `Dalla settimana ${isoWeek(range.from).number} (${weekDateLabel(range.from)}) alla ${isoWeek(shiftWeekDate(range.to, -7)).number} (${weekDateLabel(shiftWeekDate(range.to, -7))})` : first ? `Inizio: ${weekDateLabel(first)}. Scegli la settimana finale.` : 'Scegli la prima e l’ultima settimana.'}
    </div>
    <div className="mb-3 text-[10px] text-muted-foreground">vuota · con ore · <span className="border-l-2 border-study-learning pl-1">cambia qui</span></div>
    <div className="flex justify-end gap-2">
      <button type="button" onClick={onClose} className="rounded-md border px-2 py-1">Annulla</button>
      <button type="button" disabled={!range} onClick={() => range && onConfirm(range)} className="rounded-md bg-primary px-2 py-1 text-primary-foreground disabled:opacity-40">Modifica queste settimane</button>
    </div>
  </div>
}
