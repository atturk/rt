import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ClipboardCheck, ClipboardPaste, Copy } from 'lucide-react'
import { calendarApi, usePasteCalendar, type CalendarWeekView, type CalendarYearWeek } from '@/api/calendar'
import { errorMessage } from '@/api/client'
import { IconButton } from '@/components/ui/icon-button'
import { Button } from '@/components/ui/button'
import { copyWeek, useWeekClipboard } from './weekClipboard'
import { isoWeek } from './weekRange'

export function CalendarClipboardActions({ week, yearWeeks, selected, annual }: {
  week?: CalendarWeekView; yearWeeks: CalendarYearWeek[]; selected: string[]; annual: boolean
}) {
  const clipboard = useWeekClipboard()
  const paste = usePasteCalendar()
  const [notice, setNotice] = useState<'copy' | 'paste' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ weeks: string[]; conflicts: number; entries: NonNullable<typeof clipboard>['entries'] } | null>(null)
  const [busy, setBusy] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useEffect(() => {
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setConfirm(null) }
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setConfirm(null) }
    window.addEventListener('pointerdown', close); window.addEventListener('keydown', key)
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', key) }
  }, [])
  const targets = annual ? selected : week ? [week.start_date] : []
  const source = annual ? (selected.length === 1 ? selected[0] : null) : week?.start_date
  const hasHours = annual ? yearWeeks.some(w => w.start_date === source && w.days.some(d => (d.events ?? []).length)) : !!week?.days.some(d => (d.events ?? []).length)
  const unavailable = !clipboard ? 'Appunti vuoti' : targets.length === 0 ? 'Seleziona almeno una settimana' : targets.length === 1 && targets[0] === clipboard.sourceStart ? 'È la settimana copiata' : null
  const showNotice = (value: 'copy' | 'paste') => {
    setNotice(value)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setNotice(null), 1200)
  }
  async function save(weeks: string[], entries: NonNullable<typeof clipboard>['entries']) {
    setError(null)
    try { await paste.mutateAsync({ weeks, entries }); setConfirm(null); showNotice('paste') }
    catch (error) { setError(errorMessage(error)) }
  }
  return <div ref={root} className="relative flex items-center">
    <IconButton icon={Copy} label="Copia lo stampo di questa settimana" unavailable={!source || !hasHours ? 'Seleziona una settimana con ore' : busy ? 'Copia in corso' : null} onClick={() => {
      if (!source) return
      setBusy(true); setError(null)
      void (source === week?.start_date ? Promise.resolve(week) : calendarApi.getWeek(source)).then(data => { copyWeek(data); showNotice('copy') })
        .catch(error => setError(errorMessage(error))).finally(() => setBusy(false))
    }} />
    <IconButton icon={ClipboardPaste} label={clipboard ? `Incolla lo stampo della settimana ${isoWeek(clipboard.sourceStart).number}` : 'Incolla lo stampo'}
      unavailable={paste.isPending ? 'Incolla in corso' : unavailable} onClick={() => {
        if (!clipboard || !targets.length) return
        const weeks = annual ? yearWeeks.filter(w => targets.includes(w.start_date)) : week ? [week] : []
        const conflicts = weeks.filter(w => w.days.some(d => (d.events ?? []).some(e => !e.is_recorded && e.status === 'seguire'))).length
        if (conflicts) setConfirm({ weeks: [...targets], conflicts, entries: clipboard.entries })
        else void save(targets, clipboard.entries)
      }} />
    {confirm && <div role="dialog" aria-label="Sostituisci orario" className="absolute right-0 top-full z-60 mt-2 w-72 rounded-lg border bg-card p-3 text-sm shadow-panel">
      <div className="flex gap-2"><AlertTriangle aria-hidden className="size-5 shrink-0 text-warning" /><p>{annual ? `${confirm.conflicts} settimane hanno già un orario. Sostituirlo?` : 'Questa settimana ha già un orario. Sostituirlo?'}</p></div>
      <div className="mt-3 flex justify-end gap-2"><Button onClick={() => setConfirm(null)}>Annulla</Button><Button disabled={paste.isPending} onClick={() => void save(confirm.weeks, confirm.entries)}>Sostituisci</Button></div>
    </div>}
    {error && <p role="alert" className="absolute right-0 top-full z-60 w-72 rounded border bg-card p-2 text-sm text-danger">{error}</p>}
    {notice && <div className="fixed left-1/2 top-16 z-60 -translate-x-1/2 rounded-lg border bg-card p-3 shadow-panel" data-testid="calendar-clipboard-notice" aria-label={notice === 'copy' ? 'Stampo copiato' : 'Stampo incollato'}>
      {notice === 'copy' ? <Copy className="size-6" aria-hidden /> : <ClipboardCheck className="size-6" aria-hidden />}
    </div>}
  </div>
}
