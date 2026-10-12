import { useState } from 'react'
import {
  Calendar as CalendarIcon,
  CalendarRange,
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
  useCreateOverride,
  useCreateTemplateEntry,
  useDeleteOverride,
  useDeleteTemplateEntry,
  useLinkLesson,
  useSetDayState,
  useSetEntryState,
  type CalendarDayView,
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
  type PopupAnchor,
} from '@/components/calendar/CalendarPopups'
import { CalendarWeekGrid } from '@/components/calendar/CalendarWeekGrid'
import { CalendarDayList } from '@/components/calendar/CalendarDayList'

function shiftDate(isoDate: string, daysOffset: number): string {
  const d = new Date(isoDate)
  d.setDate(d.getDate() + daysOffset)
  return d.toISOString().slice(0, 10)
}

function getTodayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export function CalendarPage() {
  const isPhone = useIsPhone()
  const [currentDate, setCurrentDate] = useState(getTodayIso)
  const [desktopView, setDesktopView] = useState<'week' | 'day'>('week')
  const [selectedDayIndex, setSelectedDayIndex] = useState(0)
  const [editing, setEditing] = useState<'week' | 'tpl' | null>(null)

  // Popups state
  const [activeEvent, setActiveEvent] = useState<{
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

  // API queries & mutations
  const weekQuery = useCalendarWeek(currentDate)
  const createTpl = useCreateTemplateEntry()
  const deleteTpl = useDeleteTemplateEntry()
  const createOv = useCreateOverride()
  const deleteOv = useDeleteOverride()
  const setDayStateMutation = useSetDayState()
  const setEntryStateMutation = useSetEntryState()
  const linkLessonMutation = useLinkLesson()

  const week = weekQuery.data
  const days = week?.days ?? []

  function closeAllPopups() {
    setActiveEvent(null)
    setActiveDayMenu(null)
    setInfoAnchor(null)
    setAddSlot(null)
  }

  function handlePrev() {
    closeAllPopups()
    setCurrentDate((cur) => shiftDate(cur, isPhone || desktopView === 'day' ? -1 : -7))
  }

  function handleNext() {
    closeAllPopups()
    setCurrentDate((cur) => shiftDate(cur, isPhone || desktopView === 'day' ? 1 : 7))
  }

  function handleToday() {
    closeAllPopups()
    setCurrentDate(getTodayIso())
  }

  function handleRemoveEvent(ev: CalendarEventView) {
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
    } else if (editing === 'tpl') {
      if (ev.template_entry_id) {
        deleteTpl.mutate(ev.template_entry_id)
      } else if (ev.override_id) {
        deleteOv.mutate(ev.override_id)
      }
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background">
      {/* Header barra calendario */}
      <header className="flex h-(--header-height) shrink-0 items-center gap-1 border-b border-border px-3 sm:px-4">
        <h2 className="mr-2 text-base font-semibold">Calendario</h2>

        <IconButton
          label="Settimana precedente"
          icon={ChevronLeft}
          side="bottom"
          onClick={handlePrev}
        />

        <span className="min-w-[130px] sm:min-w-[160px] text-center font-mono text-sm font-semibold text-foreground">
          {week?.label || 'Caricamento…'}
        </span>

        <IconButton
          label="Settimana successiva"
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

        {/* Matita di modifica orario che si divide in due icone */}
        {!isPhone && (
          <div
            className={`group flex items-center rounded-lg transition-colors ${
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

                {/* All'hover/focus compaiono le due opzioni di modifica */}
                <div className="hidden group-hover:flex items-center gap-0.5 animate-in fade-in">
                  <IconButton
                    label="Modifica solo questa settimana"
                    icon={CalendarRange}
                    side="bottom"
                    onClick={() => {
                      closeAllPopups()
                      setEditing('week')
                    }}
                  />
                  <IconButton
                    label="Modifica la settimana tipo, da questa settimana in poi"
                    icon={CalendarSync}
                    side="bottom"
                    onClick={() => {
                      closeAllPopups()
                      setEditing('tpl')
                    }}
                  />
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
                  onClick={() => setEditing('week')}
                />
                <IconButton
                  label="Modifica la settimana tipo, da questa settimana in poi"
                  icon={CalendarSync}
                  side="bottom"
                  active={editing === 'tpl'}
                  className={editing === 'tpl' ? 'bg-primary text-primary-foreground' : undefined}
                  onClick={() => setEditing('tpl')}
                />
                <IconButton
                  label="Fatto"
                  icon={Check}
                  side="bottom"
                  className="bg-primary text-primary-foreground hover:opacity-90 ml-1"
                  onClick={() => {
                    closeAllPopups()
                    setEditing(null)
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
            editing={editing}
            selectedEventKey={activeEvent?.event.key ?? null}
            onOpenEvent={(event, anchor) => {
              closeAllPopups()
              setActiveEvent({ event, anchor })
            }}
            onOpenDayMenu={(day, anchor) => {
              closeAllPopups()
              setActiveDayMenu({ day, anchor })
            }}
            onOpenAdd={(day, hour, anchor) => {
              closeAllPopups()
              setAddSlot({ day, hour, anchor })
            }}
            onRemoveEvent={handleRemoveEvent}
          />
        )}

        {week && (isPhone || desktopView === 'day') && (
          <CalendarDayList
            days={days}
            selectedDayIndex={selectedDayIndex}
            onSelectDayIndex={setSelectedDayIndex}
            onOpenEvent={(event, anchor) => {
              closeAllPopups()
              setActiveEvent({ event, anchor })
            }}
          />
        )}
      </div>

      {/* Popups */}
      {activeEvent && (
        <EventPopup
          event={activeEvent.event}
          anchor={activeEvent.anchor}
          onClose={() => setActiveEvent(null)}
          onStatusChange={(status) => {
            setEntryStateMutation.mutate({
              date: activeEvent.event.date,
              entry_key: activeEvent.event.key,
              status,
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
              status,
            })
          }}
        />
      )}

      {infoAnchor && week && (
        <WeekInfoPopup
          weekLabel={week.label}
          weekNumber={week.week_number}
          summary={week.summary}
          anchor={infoAnchor}
          onClose={() => setInfoAnchor(null)}
        />
      )}

      {addSlot && editing && week && (
        <AddEventPopup
          scope={editing}
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
            } else if (editing === 'tpl') {
              createTpl.mutate({
                day_of_week: addSlot.day.day_of_week,
                start_time: startTime,
                end_time: endTime,
                materia,
                docente,
                valid_from: addSlot.day.date,
              })
            }
          }}
        />
      )}
    </div>
  )
}
