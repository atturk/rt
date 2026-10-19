import { useState } from 'react'
import {
  Calendar as CalendarIcon,
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
import { Tooltip } from '@/components/ui/tooltip'
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
import { WeekRangePopup } from '@/components/calendar/WeekRangePopup'
import { weekRangeLabel, type WeekRange } from '@/components/calendar/weekRange'

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

export function CalendarPage() {
  const isPhone = useIsPhone()
  const [currentDate, setCurrentDate] = useState(getTodayIso)
  const [desktopView, setDesktopView] = useState<'week' | 'day'>('week')
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
    setRangeAnchor(null)
    setActiveEvent(null)
    setActiveDayMenu(null)
    setInfoAnchor(null)
    setAddSlot(null)
    setEditSlot(null)
  }

  function handlePrev() {
    closeAllPopups()
    setCurrentDate((cur) => (dayMode ? shiftWeekday(cur, -1) : shiftDate(cur, -7)))
  }

  function handleNext() {
    closeAllPopups()
    setCurrentDate((cur) => (dayMode ? shiftWeekday(cur, 1) : shiftDate(cur, 7)))
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
        // La nuova ora vale nelle date scelte, poi si toglie la versione precedente.
        await createTpl.mutateAsync({
          ...fields,
          day_of_week: ev.day_of_week,
          valid_from: templateDates?.from ?? week.start_date,
          ...(templateDates?.to ? { valid_to: templateDates.to } : {}),
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
      <header className="flex h-(--header-height) shrink-0 items-center gap-1 border-b border-border px-3 sm:px-4">
        <h1 className="mr-2 text-base font-semibold">Calendario</h1>

        <IconButton
          label={dayMode ? 'Giorno precedente' : 'Settimana precedente'}
          icon={ChevronLeft}
          side="bottom"
          onClick={handlePrev}
        />

        <div className="min-w-[130px] sm:min-w-[160px] text-center">
          <span data-testid="calendar-week-label" className="font-mono text-sm font-semibold text-foreground">
            {week?.label || 'Caricamento…'}
          </span>
          {editing === 'range' && rangeEdit && <button type="button" onClick={openRange}
            className="mx-auto block max-w-40 truncate rounded-full bg-muted px-2 text-[10px]" aria-label="Cambia intervallo di settimane">
            {weekRangeLabel(rangeEdit)}
          </button>}
        </div>

        <IconButton
          label={dayMode ? 'Giorno successivo' : 'Settimana successiva'}
          icon={ChevronRight}
          side="bottom"
          onClick={handleNext}
        />

        <IconButton label="Oggi" icon={CalendarIcon} side="bottom" onClick={handleToday} />

        <div className="flex-1" />

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

        {/* Matita con le tre modalità di modifica dell'orario */}
        {!isPhone && (
          <div
            className={`group flex items-center rounded-lg transition-colors focus-within:bg-muted ${
              editing ? 'bg-muted' : 'hover:bg-muted'
            }`}
          >
            {!editing ? (
              <>
                <Tooltip content="Modifica orario" side="bottom">
                  {(t) => (
                    <button
                      type="button"
                      className="inline-flex size-(--control-size) items-center justify-center rounded-md text-foreground group-hover:hidden"
                      aria-label="Modifica orario"
                      {...t}
                    >
                      <Pencil className="size-[18px]" />
                    </button>
                  )}
                </Tooltip>

                {/* All'hover/focus compaiono le opzioni di modifica */}
                <div className="hidden group-hover:flex group-focus-within:flex items-center gap-0.5 animate-in fade-in">
                  <IconButton
                    label="Modifica solo questa settimana"
                    icon={CalendarRange}
                    side="bottom"
                    onClick={() => beginEditing('week')}
                  />
                  <IconButton
                    label="Modifica la settimana tipo, da questa settimana in poi"
                    icon={CalendarSync}
                    side="bottom"
                    onClick={() => beginEditing('tpl')}
                  />
                  <IconButton label="Modifica la settimana tipo in un intervallo di settimane" icon={CalendarDays} side="bottom" onClick={openRange} />
                </div>
              </>
            ) : (
              <div className="flex items-center gap-0.5">
                <IconButton
                  label="Modifica solo questa settimana"
                  icon={CalendarRange}
                  side="bottom"
                  active={editing === 'week'}
                  className={editing === 'week' ? 'bg-primary text-primary-foreground' : undefined}
                  onClick={() => beginEditing('week')}
                />
                <IconButton
                  label="Modifica la settimana tipo, da questa settimana in poi"
                  icon={CalendarSync}
                  side="bottom"
                  active={editing === 'tpl'}
                  className={editing === 'tpl' ? 'bg-primary text-primary-foreground' : undefined}
                  onClick={() => beginEditing('tpl')}
                />
                <IconButton label="Modifica la settimana tipo in un intervallo di settimane" icon={CalendarDays} side="bottom" active={editing === 'range'} onClick={openRange} />
                <IconButton
                  label="Fatto"
                  icon={Check}
                  side="bottom"
                  className="bg-primary text-primary-foreground hover:opacity-90 ml-1"
                  onClick={() => {
                    closeAllPopups()
                    setEditing(null)
                    setRangeEdit(null)
                  }}
                />
              </div>
            )}
          </div>
        )}

        {/* Selettore vista Settimana / Giorno su desktop */}
        {!isPhone && (
          <div className="ml-2 flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
            <IconButton
              label="Settimana"
              icon={Columns2}
              side="bottom"
              active={desktopView === 'week'}
              onClick={() => setDesktopView('week')}
            />
            <IconButton
              label="Giorno"
              icon={Rows3}
              side="bottom"
              active={desktopView === 'day'}
              onClick={() => setDesktopView('day')}
            />
          </div>
        )}
      </header>

      {outsideRange && <div className="border-b px-4 py-1 text-xs text-muted-foreground" role="status">Fuori dall'intervallo scelto</div>}
      {/* Corpo del calendario */}
      <div className="flex flex-1 min-h-0 overflow-auto">
        {weekQuery.isPending && (
          <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
            Caricamento calendario…
          </div>
        )}

        {weekQuery.isError && (
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
