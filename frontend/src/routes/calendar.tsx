import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  Calendar as CalendarIcon,
  CalendarSearch,
  LayoutGrid,
  ListChecks,
  CalendarRange,
  CalendarDays,
  CalendarSync,
  Check,
  ChevronLeft,
  ChevronRight,
  Columns2,
  Info,
  Pencil,
  Rows3,
} from 'lucide-react'

import {
  useCalendarWeek,
  useCalendarYear,
  useCalendarTemplate,
  useCreateOverride,
  useCreateTemplateEntry,
  useDeleteOverride,
  useDeleteTemplateEntry,
  useLinkLesson,
  useSetDayState,
  useSetEntryState,
  type CalendarDayStateSet,
  type CalendarDayView,
  type CalendarEntryStateSet,
  type CalendarEventView,
} from '@/api/calendar'
import { IconButton } from '@/components/ui/icon-button'
import { useIsPhone } from '@/lib/phone'
import {
  AddEventPopup,
  DayMenuPopup,
  EventPopup,
  WeekInfoPopup,
  type EventFormValues,
  type PopupAnchor,
} from '@/components/calendar/CalendarPopups'
import { CalendarWeekGrid } from '@/components/calendar/CalendarWeekGrid'
import { CalendarDayList } from '@/components/calendar/CalendarDayList'
import { CalendarYearView } from '@/components/calendar/CalendarYearView'
import { CalendarClipboardActions } from '@/components/calendar/CalendarClipboardActions'
import { WeekRangePopup } from '@/components/calendar/WeekRangePopup'
import { academicYear, academicWeeks, weekRangeLabel, type WeekRange } from '@/components/calendar/weekRange'

// Date in ora locale: toISOString() passa per UTC e sbaglia giorno vicino a mezzanotte e al cambio d'ora.
function toLocalIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function fromLocalIso(isoDate: string): Date {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function shiftDate(isoDate: string, daysOffset: number): string {
  const d = fromLocalIso(isoDate)
  d.setDate(d.getDate() + daysOffset)
  return toLocalIso(d)
}

// Un giorno avanti o indietro saltando sabato e domenica (il calendario mostra lun–ven).
function shiftWeekday(isoDate: string, step: 1 | -1): string {
  let next = shiftDate(isoDate, step)
  while ([0, 6].includes(fromLocalIso(next).getDay())) next = shiftDate(next, step)
  return next
}

function getTodayIso(): string {
  return toLocalIso(new Date())
}

const hoverSnapshot = () => typeof window.matchMedia === 'function' ? window.matchMedia('(hover: hover)').matches : true
const subscribeHover = (change: () => void) => {
  const media = window.matchMedia?.('(hover: hover)')
  media?.addEventListener('change', change)
  return () => media?.removeEventListener('change', change)
}

export function CalendarPage() {
  const isPhone = useIsPhone()
  const hover = useSyncExternalStore(subscribeHover, hoverSnapshot, () => true)
  const [currentDate, setCurrentDate] = useState(getTodayIso)
  const [desktopView, setDesktopView] = useState<'week' | 'day' | 'year'>(() => {
    try { const saved = sessionStorage.getItem('rt:calendar-view'); return saved === 'day' || saved === 'year' ? saved : 'week' } catch { return 'week' }
  })
  const setView = (view: 'week' | 'day' | 'year') => {
    setDesktopView(view)
    try { sessionStorage.setItem('rt:calendar-view', view) } catch { /* La vista resta nella pagina. */ }
    setEditing(null)
    setMultiple(false)
    setMenuOpen(false)
    closeAllPopups()
  }
  const [jumpAnchor, setJumpAnchor] = useState<PopupAnchor | null>(null)
  const [selectedWeeks, setSelectedWeeks] = useState<string[]>([])
  const [multiple, setMultiple] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const pencil = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!pencil.current?.contains(event.target as Node)) setMenuOpen(false) }
    window.addEventListener('pointerdown', outside)
    return () => window.removeEventListener('pointerdown', outside)
  }, [])
  const annual = !isPhone && desktopView === 'year'
  const year = Math.max(2025, Math.min(2035, academicYear(currentDate)))
  const yearQuery = useCalendarYear(academicWeeks(year)[0], annual)
  const [editing, setEditing] = useState<'week' | 'tpl' | 'range' | null>(null)
  const [rangeEdit, setRangeEdit] = useState<WeekRange | null>(null)
  const [rangeAnchor, setRangeAnchor] = useState<PopupAnchor | null>(null)

  // Popups state: dell'ora si tiene solo la chiave, i dati si leggono sempre dalla settimana aggiornata
  const [activeEventRef, setActiveEvent] = useState<{
    event: CalendarEventView
    anchor: PopupAnchor
  } | null>(null)
  const [activeDayMenu, setActiveDayMenu] = useState<{
    day: CalendarDayView
    anchor: PopupAnchor
  } | null>(null)
  const [infoAnchor, setInfoAnchor] = useState<PopupAnchor | null>(null)
  const [addSlot, setAddSlot] = useState<{
    day: CalendarDayView
    hour: number
    anchor: PopupAnchor
  } | null>(null)
  const [editSlot, setEditSlot] = useState<{
    event: CalendarEventView
    anchor: PopupAnchor
  } | null>(null)

  // API queries & mutations
  const weekQuery = useCalendarWeek(currentDate)
  const templateQuery = useCalendarTemplate()
  const createTpl = useCreateTemplateEntry()
  const deleteTpl = useDeleteTemplateEntry()
  const createOv = useCreateOverride()
  const deleteOv = useDeleteOverride()
  const setDayStateMutation = useSetDayState()
  const setEntryStateMutation = useSetEntryState()
  const linkLessonMutation = useLinkLesson()

  const week = weekQuery.data
  const days = week?.days ?? []
  const outsideRange = editing === 'range' && (!rangeEdit || !week || week.start_date < rangeEdit.from || week.start_date >= rangeEdit.to)
  const gridEditing = outsideRange ? null : editing
  const templateDates: { from: string; to?: string } | null = editing === 'range' ? rangeEdit : week ? { from: week.start_date } : null
  const liveEvent = activeEventRef
    ? days
        .flatMap((d) => d.events)
        .find((ev) => ev?.key === activeEventRef.event.key && ev?.date === activeEventRef.event.date)
    : undefined
  const activeEvent = activeEventRef
    ? { event: liveEvent ?? activeEventRef.event, anchor: activeEventRef.anchor }
    : null
  // Il giorno mostrato in vista giorno segue la data corrente (oggi all'apertura).
  const selectedDayIndex = Math.max(
    0,
    days.findIndex((d) => d.date === currentDate),
  )
  const dayMode = isPhone || desktopView === 'day'

  function closeAllPopups() {
    setJumpAnchor(null)
    setRangeAnchor(null)
    setActiveEvent(null)
    setActiveDayMenu(null)
    setInfoAnchor(null)
    setAddSlot(null)
    setEditSlot(null)
  }

  function handlePrev() {
    closeAllPopups()
    setCurrentDate((cur) => annual ? academicWeeks(Math.max(2025, year - 1))[0] : dayMode ? shiftWeekday(cur, -1) : shiftDate(cur, -7))
  }

  function handleNext() {
    closeAllPopups()
    setCurrentDate((cur) => annual ? academicWeeks(Math.min(2035, year + 1))[0] : dayMode ? shiftWeekday(cur, 1) : shiftDate(cur, 7))
  }

  function handleToday() {
    closeAllPopups()
    setCurrentDate(getTodayIso())
  }

  function handleRemoveEvent(ev: CalendarEventView) {
    if (outsideRange) return
    if (editing === 'week') {
      if (ev.override_id) {
        deleteOv.mutate(ev.override_id)
      } else if (ev.template_entry_id) {
        createOv.mutate({
          date: ev.date,
          action: 'removed',
          template_entry_id: ev.template_entry_id,
        })
      }
    } else if (editing === 'tpl' || editing === 'range') {
      if (ev.template_entry_id) {
        // Si applica solo alla validità scelta; gli stati prima e dopo restano conservati.
        deleteTpl.mutate({ id: ev.template_entry_id, ...templateDates })
      } else if (ev.override_id) {
        deleteOv.mutate(ev.override_id)
      }
    }
  }

  // Modifica di un'ora: si crea la versione nuova e poi si toglie la vecchia, così un errore a metà
  // non fa sparire l'ora.
  async function handleEditEvent(ev: CalendarEventView, data: EventFormValues) {
    if (!week || outsideRange) return
    const unchanged =
      data.materia === ev.materia &&
      data.startTime === ev.start_time &&
      data.endTime === ev.end_time &&
      (data.docente ?? '') === (ev.docente ?? '')
    if (unchanged) return
    const fields = {
      start_time: data.startTime,
      end_time: data.endTime,
      materia: data.materia,
      docente: data.docente,
    }
    try {
      if ((editing === 'tpl' || editing === 'range') && ev.template_entry_id) {
        // La nuova ora vale nelle date scelte, ma solo dove valeva la vecchia; poi si toglie
        // la versione precedente.
        const old = templateQuery.data?.find(t => t.id === ev.template_entry_id)
        const chosenFrom = templateDates?.from ?? week.start_date
        const from = old?.valid_from && old.valid_from > chosenFrom ? old.valid_from : chosenFrom
        const ends = [templateDates?.to, old?.valid_to].filter((d): d is string => !!d).sort()
        const to = ends[0]
        if (to && to <= from) return
        await createTpl.mutateAsync({
          ...fields,
          day_of_week: ev.day_of_week,
          valid_from: from,
          ...(to ? { valid_to: to } : {}),
        })
        await deleteTpl.mutateAsync({ id: ev.template_entry_id, ...templateDates })
      } else if (ev.template_entry_id) {
        // Solo questa settimana: una modifica puntuale dell'ora della settimana tipo, che
        // sostituisce quella eventualmente già presente per lo stesso giorno.
        await createOv.mutateAsync({
          ...fields,
          date: ev.date,
          action: 'modified',
          template_entry_id: ev.template_entry_id,
        })
        if (ev.override_id) await deleteOv.mutateAsync(ev.override_id)
      } else if (ev.override_id) {
        // Ora aggiunta solo per questa settimana: si sostituisce con una nuova aggiunta.
        await createOv.mutateAsync({ ...fields, date: ev.date, action: 'added' })
        await deleteOv.mutateAsync(ev.override_id)
      }
    } catch {
      // Come per aggiungere e togliere ore, l'errore non ha un avviso dedicato: la settimana
      // mostrata resta quella salvata sul server.
    }
  }

  function openRange(event: React.MouseEvent<HTMLButtonElement>) {
    closeAllPopups()
    const rect = event.currentTarget.getBoundingClientRect()
    setRangeAnchor({ x: rect.left, y: rect.bottom, width: rect.width, height: rect.height })
  }

  function beginEditing(mode: 'week' | 'tpl') {
    closeAllPopups()
    setEditing(mode)
    setRangeEdit(null)
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background">
      {/* Header barra calendario */}
      <header className="relative flex h-(--header-height) shrink-0 items-center gap-1 border-b border-border px-3 sm:px-4">
        <h1 className="mr-2 text-base font-semibold max-md:sr-only">Calendario</h1>

        <IconButton
          label={annual ? 'Anno precedente' : dayMode ? 'Giorno precedente' : 'Settimana precedente'}
          icon={ChevronLeft}
          side="bottom"
          onClick={handlePrev}
        />

        <div className="min-w-[130px] sm:min-w-[160px] text-center max-md:min-w-0 max-md:flex-1">
          <span data-testid="calendar-week-label" className="block truncate font-mono text-sm font-semibold text-foreground max-md:text-[11px]">
            {annual ? `${year}/${String(year + 1).slice(-2)}` : week?.label || 'Caricamento…'}
          </span>
          {editing === 'range' && rangeEdit && <button type="button" onClick={openRange}
            className="mx-auto block max-w-40 truncate rounded-full bg-muted px-2 text-[10px]" aria-label="Cambia intervallo di settimane">
            {weekRangeLabel(rangeEdit)}
          </button>}
        </div>

        <IconButton
          label={annual ? 'Anno successivo' : dayMode ? 'Giorno successivo' : 'Settimana successiva'}
          icon={ChevronRight}
          side="bottom"
          onClick={handleNext}
        />

        <IconButton label="Oggi" icon={CalendarIcon} side="bottom" onClick={handleToday} />
        <IconButton label="Vai alla settimana" icon={CalendarSearch} onClick={event => {
          closeAllPopups()
          const rect = event.currentTarget.getBoundingClientRect()
          setJumpAnchor({ x: rect.left, y: rect.bottom, width: rect.width, height: rect.height })
        }} />

        <div className="flex-1 max-md:hidden" />

        {/* Bottone ⓘ Riepilogo settimana */}
        <IconButton
          label="Riepilogo della settimana"
          icon={Info}
          side="bottom"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            setInfoAnchor({
              x: rect.left,
              y: rect.bottom,
              width: rect.width,
              height: rect.height,
            })
          }}
        />

        <div ref={pencil} className={`group flex items-center rounded-lg focus-within:bg-muted ${editing || menuOpen || multiple ? 'bg-muted' : 'hover:bg-muted'}`}>
          <IconButton label="Modifica orario" icon={Pencil} aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}
            className={hover && (editing || multiple || menuOpen) ? 'hidden' : hover ? 'group-hover:hidden' : undefined} />
          <div className={`${menuOpen || hover && (editing || multiple) ? 'flex' : 'hidden [@media(hover:hover)]:group-hover:flex [@media(hover:hover)]:group-focus-within:flex'} items-center gap-0.5 ${hover ? '' : 'absolute right-3 top-full z-50 mt-1 rounded-lg border bg-card p-1 shadow-panel'}`}>
            <CalendarClipboardActions week={week} yearWeeks={yearQuery.data ?? []} selected={selectedWeeks} annual={annual} />
            {annual ? <IconButton icon={ListChecks} label="Seleziona più settimane" active={multiple} onClick={() => { setMultiple(value => !value); setMenuOpen(true) }} /> : <>
              <IconButton label="Modifica solo questa settimana" icon={CalendarRange} active={editing === 'week'} onClick={() => beginEditing('week')} />
              <IconButton label="Modifica la settimana tipo, da questa settimana in poi" icon={CalendarSync} active={editing === 'tpl'} onClick={() => beginEditing('tpl')} />
              <IconButton label="Modifica la settimana tipo in un intervallo di settimane" icon={CalendarDays} active={editing === 'range'} onClick={openRange} />
            </>}
            {(editing || multiple || menuOpen) && <IconButton label="Fatto" icon={Check} onClick={() => {
              closeAllPopups(); setEditing(null); setRangeEdit(null); setMultiple(false); setMenuOpen(false)
            }} />}
          </div>
        </div>

        {/* Selettore vista Settimana / Giorno su desktop */}
        {!isPhone && (
          <div className="ml-2 flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
            <IconButton
              label="Settimana"
              icon={Columns2}
              side="bottom"
              active={desktopView === 'week'}
              onClick={() => setView('week')}
            />
            <IconButton
              label="Giorno"
              icon={Rows3}
              side="bottom"
              active={desktopView === 'day'}
              onClick={() => setView('day')}
            />
            <IconButton label="Anno" icon={LayoutGrid} active={annual} onClick={() => { setView('year'); setSelectedWeeks([]) }} />
          </div>
        )}
      </header>

      {outsideRange && <div className="border-b px-4 py-1 text-xs text-muted-foreground" role="status">Fuori dall'intervallo scelto</div>}
      {/* Corpo del calendario */}
      <div className="flex flex-1 min-h-0 overflow-auto">
        {annual && <>
          {yearQuery.isPending && <span className="sr-only" role="status">Caricamento calendario</span>}
          {yearQuery.isError && <p role="alert" className="p-4 text-danger">Errore nel caricamento del calendario</p>}
          <CalendarYearView weeks={yearQuery.data ?? []} selected={selectedWeeks} onSelect={monday => {
            setSelectedWeeks(current => multiple ? current.includes(monday) ? current.filter(w => w !== monday) : [...current, monday] : current.length === 1 && current[0] === monday ? [] : [monday])
          }} onOpen={monday => { setCurrentDate(monday); setView('week'); setMultiple(false) }} />
        </>}
        {!annual && weekQuery.isPending && (
          <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
            Caricamento calendario…
          </div>
        )}

        {!annual && weekQuery.isError && (
          <div className="flex flex-1 items-center justify-center p-8 text-sm text-danger">
            Errore nel caricamento del calendario: {weekQuery.error.message}
          </div>
        )}

        {week && !isPhone && desktopView === 'week' && (
          <CalendarWeekGrid
            days={days}
            editing={gridEditing}
            readOnly={outsideRange}
            selectedEventKey={activeEvent?.event.key ?? null}
            onOpenEvent={(event, anchor) => {
              if (outsideRange) return
              closeAllPopups()
              setActiveEvent({ event, anchor })
            }}
            onOpenDayMenu={(day, anchor) => {
              if (outsideRange) return
              closeAllPopups()
              setActiveDayMenu({ day, anchor })
            }}
            onOpenAdd={(day, hour, anchor) => {
              closeAllPopups()
              setAddSlot({ day, hour, anchor })
            }}
            onRemoveEvent={handleRemoveEvent}
            onEditEvent={(event, anchor) => {
              closeAllPopups()
              setEditSlot({ event, anchor })
            }}
          />
        )}

        {week && (isPhone || desktopView === 'day') && (
          <CalendarDayList
            days={days}
            selectedDayIndex={selectedDayIndex}
            readOnly={outsideRange}
            onSelectDayIndex={(i) => {
              closeAllPopups()
              if (days[i]) setCurrentDate(days[i].date)
            }}
            onOpenEvent={(event, anchor) => {
              if (outsideRange) return
              closeAllPopups()
              setActiveEvent({ event, anchor })
            }}
          />
        )}
      </div>

      {/* Popups */}
      {jumpAnchor && <WeekRangePopup navigate anchor={jumpAnchor} currentDate={currentDate} entries={templateQuery.data ?? []}
        onClose={() => setJumpAnchor(null)} onConfirm={range => { closeAllPopups(); setCurrentDate(range.from); if (annual) setView('week') }} />}

      {rangeAnchor && <WeekRangePopup anchor={rangeAnchor} currentDate={currentDate} entries={templateQuery.data ?? []} initial={rangeEdit}
        onClose={() => setRangeAnchor(null)} onConfirm={range => {
          closeAllPopups(); setRangeEdit(range); setEditing('range'); setCurrentDate(range.from)
        }} />}

      {activeEvent && (
        <EventPopup
          event={activeEvent.event}
          anchor={activeEvent.anchor}
          onClose={() => setActiveEvent(null)}
          onStatusChange={(status) => {
            setEntryStateMutation.mutate({
              date: activeEvent.event.date,
              entry_key: activeEvent.event.key,
              status: status as CalendarEntryStateSet['status'],
              template_entry_id: activeEvent.event.template_entry_id ?? undefined,
              override_id: activeEvent.event.override_id ?? undefined,
            })
          }}
          onNoteSave={(note) => {
            setEntryStateMutation.mutate({
              date: activeEvent.event.date,
              entry_key: activeEvent.event.key,
              note,
              template_entry_id: activeEvent.event.template_entry_id ?? undefined,
              override_id: activeEvent.event.override_id ?? undefined,
            })
          }}
          onLinkLesson={(lessonId) => {
            linkLessonMutation.mutate({
              date: activeEvent.event.date,
              entry_key: activeEvent.event.key,
              lesson_id: lessonId,
              template_entry_id: activeEvent.event.template_entry_id ?? undefined,
              override_id: activeEvent.event.override_id ?? undefined,
            })
          }}
        />
      )}

      {activeDayMenu && (
        <DayMenuPopup
          day={activeDayMenu.day}
          anchor={activeDayMenu.anchor}
          onClose={() => setActiveDayMenu(null)}
          onSetDayState={(status) => {
            setDayStateMutation.mutate({
              date: activeDayMenu.day.date,
              status: status as CalendarDayStateSet['status'],
            })
          }}
        />
      )}

      {infoAnchor && week && (
        <WeekInfoPopup
          weekLabel={week.label}
          weekStart={week.start_date}
          weekNumber={week.week_number}
          summary={week.summary}
          anchor={infoAnchor}
          onClose={() => setInfoAnchor(null)}
        />
      )}

      {addSlot && editing && week && !outsideRange && (
        <AddEventPopup
          scope={editing}
          rangeLabel={rangeEdit ? weekRangeLabel(rangeEdit) : undefined}
          weekNumber={week.week_number}
          defaultStartTime={`${String(Math.floor(addSlot.hour)).padStart(2, '0')}:${String(
            Math.round((addSlot.hour - Math.floor(addSlot.hour)) * 60),
          ).padStart(2, '0')}`}
          anchor={addSlot.anchor}
          onClose={() => setAddSlot(null)}
          onAdd={({ materia, startTime, endTime, docente }) => {
            if (editing === 'week') {
              createOv.mutate({
                date: addSlot.day.date,
                action: 'added',
                start_time: startTime,
                end_time: endTime,
                materia,
                docente,
              })
            } else if (editing === 'tpl' || editing === 'range') {
              createTpl.mutate({
                day_of_week: addSlot.day.day_of_week,
                start_time: startTime,
                end_time: endTime,
                materia,
                docente,
                valid_from: templateDates?.from ?? week.start_date,
                ...(templateDates?.to ? { valid_to: templateDates.to } : {}),
              })
            }
          }}
        />
      )}

      {editSlot && editing && week && !outsideRange && (
        <AddEventPopup
          key={`${editSlot.event.date}-${editSlot.event.key}`}
          scope={editing}
          rangeLabel={rangeEdit ? weekRangeLabel(rangeEdit) : undefined}
          weekNumber={week.week_number}
          initial={{
            materia: editSlot.event.materia,
            startTime: editSlot.event.start_time,
            endTime: editSlot.event.end_time,
            docente: editSlot.event.docente ?? undefined,
          }}
          anchor={editSlot.anchor}
          onClose={() => setEditSlot(null)}
          onAdd={(data) => void handleEditEvent(editSlot.event, data)}
        />
      )}
    </div>
  )
}
