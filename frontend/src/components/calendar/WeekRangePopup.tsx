import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, CircleHelp, X } from 'lucide-react'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { isMacKeyboard } from '@/lib/platform'
import type { CalendarTemplateEntryView } from '@/api/calendar'
import type { PopupAnchor } from './CalendarPopups'
import { computePopupStyle } from './popupPosition'
import { WeekYearGrid, type WeekSelectModifiers } from './WeekYearGrid'
import { contiguousRuns, expandWeekRanges, rangeBetween, shiftWeekDate, toggleWeek, type WeekRange } from './weekRange'

type CommonProps = {
  anchor: PopupAnchor
  currentDate: string
  entries: CalendarTemplateEntryView[]
  initial?: WeekRange | WeekRange[] | null
  onClose: () => void
}

export type WeekRangePopupProps =
  | (CommonProps & { navigate: true; onConfirm: (range: WeekRange) => void })
  | (CommonProps & { navigate?: false; onConfirm: (ranges: WeekRange[]) => void })

export function WeekRangePopup(props: WeekRangePopupProps) {
  const { anchor, currentDate, entries, initial, onClose } = props
  const [selected, setSelected] = useState<Set<string>>(() => new Set(expandWeekRanges(initial)))
  const [anchorWeek, setAnchorWeek] = useState<string | null>(() => expandWeekRanges(initial).at(-1) ?? null)
  const popup = useRef<HTMLDivElement>(null)
  const runs = useMemo(() => contiguousRuns(selected), [selected])

  useEffect(() => {
    function key(event: KeyboardEvent) { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }
    function outside(event: PointerEvent) { if (popup.current && !popup.current.contains(event.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    window.addEventListener('pointerdown', outside)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('pointerdown', outside) }
  }, [onClose])

  function handleWeekSelect(monday: string, { mod, shift }: WeekSelectModifiers) {
    if (shift && anchorWeek) {
      setSelected(prev => {
        const next = new Set(prev)
        for (const week of rangeBetween(anchorWeek, monday)) next.add(week)
        return next
      })
      return
    }
    if (mod) {
      setSelected(prev => toggleWeek(prev, monday))
      setAnchorWeek(monday)
      return
    }
    setSelected(new Set([monday]))
    setAnchorWeek(monday)
  }

  function handleDragStart(monday: string) {
    setSelected(new Set([monday]))
    setAnchorWeek(monday)
  }

  function handleDragMove(startWeek: string, currentWeek: string) {
    setSelected(new Set(rangeBetween(startWeek, currentWeek)))
  }

  const count = selected.size
  const countLabel = count === 1 ? '1 settimana selezionata' : `${count} settimane selezionate`
  const modKey = isMacKeyboard() ? '⌘' : 'Ctrl'
  const helpText = `Clic: una settimana · Trascina: più settimane di seguito · ${modKey}+clic: aggiungi o togli una settimana · ⇧+clic: dall'ultima scelta a questa`

  return <div
    ref={popup}
    onKeyDownCapture={event => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
    }}
    role="dialog"
    aria-label={props.navigate ? 'Vai alla settimana' : 'Intervallo di settimane'}
    data-testid="calendar-range-popup"
    style={{ ...computePopupStyle(anchor, Math.min(420, window.innerWidth - 24)), maxHeight: 'calc(100dvh - 24px)', overflowY: 'auto', top: '12px' }}
    className="rounded-xl border bg-background p-3 text-xs shadow-xl"
  >
    {props.navigate ? (
      <WeekYearGrid
        currentDate={currentDate}
        entries={entries}
        onToday={() => {
          const now = new Date()
          const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
          props.onConfirm({ from: date, to: date })
        }}
        onSelect={monday => props.onConfirm({ from: monday, to: shiftWeekDate(monday, 7) })}
      />
    ) : (
      <>
        <WeekYearGrid
          currentDate={currentDate}
          entries={entries}
          selected={selected}
          onWeekSelect={handleWeekSelect}
          onDragStart={handleDragStart}
          onDragMove={handleDragMove}
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="text-muted-foreground" aria-live="polite">{countLabel}</div>
          <div className="flex items-center gap-1">
            <Tooltip content={helpText}>
              {trigger => (
                <button
                  type="button"
                  aria-label="Aiuto sulla selezione"
                  className="inline-flex size-(--control-size) min-w-(--control-size) shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&_svg]:size-[18px] [&_svg]:stroke-[1.7]"
                  {...trigger}
                >
                  <CircleHelp aria-hidden />
                </button>
              )}
            </Tooltip>
            <IconButton icon={X} label="Annulla" onClick={onClose} />
            <IconButton icon={Check} label="Modifica queste settimane" disabled={runs.length === 0} onClick={() => runs.length > 0 && props.onConfirm(runs)} />
          </div>
        </div>
      </>
    )}
  </div>
}
