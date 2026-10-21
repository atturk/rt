import { useEffect, useRef, useState } from 'react'
import { Check, X } from 'lucide-react'
import { IconButton } from '@/components/ui/icon-button'
import type { CalendarTemplateEntryView } from '@/api/calendar'
import type { PopupAnchor } from './CalendarPopups'
import { computePopupStyle } from './popupPosition'
import { WeekYearGrid } from './WeekYearGrid'
import { selectWeekRange, shiftWeekDate, weekRangeLabel, type WeekRange } from './weekRange'

export function WeekRangePopup({ anchor, currentDate, entries, initial, onClose, onConfirm, navigate = false }: {
  anchor: PopupAnchor; currentDate: string; entries: CalendarTemplateEntryView[]; initial?: WeekRange | null
  onClose: () => void; onConfirm: (range: WeekRange) => void; navigate?: boolean
}) {
  const [first, setFirst] = useState<string | null>(initial?.from ?? null)
  const [last, setLast] = useState<string | null>(initial ? shiftWeekDate(initial.to, -7) : null)
  const popup = useRef<HTMLDivElement>(null)
  const range = first && last ? selectWeekRange(first, last) : null
  useEffect(() => {
    function key(event: KeyboardEvent) { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }
    function outside(event: PointerEvent) { if (popup.current && !popup.current.contains(event.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    window.addEventListener('pointerdown', outside)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('pointerdown', outside) }
  }, [onClose])
  return <div ref={popup} onKeyDownCapture={event => {
    if (event.key === 'Escape') { event.stopPropagation(); onClose() }
  }} role="dialog" aria-label={navigate ? 'Vai alla settimana' : 'Intervallo di settimane'} data-testid="calendar-range-popup"
    style={{ ...computePopupStyle(anchor, Math.min(420, window.innerWidth - 24)), maxHeight: 'calc(100dvh - 24px)', overflowY: 'auto', top: '12px' }}
    className="rounded-xl border bg-background p-3 text-xs shadow-xl">
    <WeekYearGrid currentDate={currentDate} entries={entries} first={first} range={range}
      onToday={navigate ? () => { const now = new Date(); const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; onConfirm({ from: date, to: date }) } : undefined}
      onSelect={monday => {
        if (navigate) { onConfirm({ from: monday, to: shiftWeekDate(monday, 7) }); return }
        if (!first || last) { setFirst(monday); setLast(null) } else setLast(monday)
      }} />
    {!navigate && <>
      <div className="sr-only" aria-live="polite">{range ? weekRangeLabel(range) : first ? 'Scegli la settimana finale' : 'Scegli la prima settimana'}</div>
      <div className="mt-2 flex justify-end gap-2">
        <IconButton icon={X} label="Annulla" onClick={onClose} />
        <IconButton icon={Check} label="Modifica queste settimane" disabled={!range} onClick={() => range && onConfirm(range)} />
      </div>
    </>}
  </div>
}
