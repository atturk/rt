import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  AlertCircle,
  Ban,
  Check,
  Clock,
  ExternalLink,
  FileText,
  GraduationCap,
  Link as LinkIcon,
  Mic,
  SkipForward,
  X,
} from 'lucide-react'
import type {
  CalendarDayView,
  CalendarEventView,
  CalendarWeekSummary,
} from '@/api/calendar'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { getSubjectColor } from './subjectColor'
import { STATUS_LABELS } from './calendarUtils'
import { useLessons } from '@/api/hooks'
import { useSubjects } from '@/api/subjects'


export type PopupAnchor = {
  x: number
  y: number
  width: number
  height: number
}

function computePopupStyle(anchor: PopupAnchor, width = 270): React.CSSProperties {
  const pad = 12
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1000
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800

  let left = anchor.x + anchor.width + 8
  if (left + width > vw - pad) {
    left = anchor.x - width - 8
  }
  if (left < pad) {
    left = pad
  }

  let top = anchor.y
  if (top + 320 > vh - pad) {
    top = Math.max(pad, vh - 330)
  }

  return {
    position: 'fixed',
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    zIndex: 60,
  }
}

// ---------------------------------------------------------------------------
// 1. Popup Evento (singola ora)
// ---------------------------------------------------------------------------

export function EventPopup({
  event,
  anchor,
  onClose,
  onStatusChange,
  onNoteSave,
  onLinkLesson,
}: {
  event: CalendarEventView
  anchor: PopupAnchor
  onClose: () => void
  onStatusChange: (status: string) => void
  onNoteSave: (note: string) => void
  onLinkLesson: (lessonId: number | null) => void
}) {
  const color = getSubjectColor(event.materia)
  const [editingNote, setEditingNote] = useState(false)
  const [noteText, setNoteText] = useState(event.note ?? '')
  const [linking, setLinking] = useState(false)
  const lessonsQuery = useLessons()
  const popupRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    function onPointerDown(e: PointerEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [onClose])

  const style = computePopupStyle(anchor, 280)
  const isRecorded = !!event.lesson

  return (
    <div
      ref={popupRef}
      style={style}
      role="dialog"
      data-testid="calendar-event-popup"
      aria-label={`Dettaglio ora ${event.materia}`}
      className="flex flex-col gap-2.5 rounded-xl border bg-background p-3 text-sm shadow-xl"
    >
      <div className="flex items-center gap-2 font-semibold">
        <span
          className="size-2.5 shrink-0 rounded-[3px]"
          style={{ backgroundColor: color }}
          aria-hidden
        />
        <span className="truncate">{event.materia}</span>
      </div>

      <div className="text-xs text-muted-foreground font-mono">
        {event.date} · {event.start_time}–{event.end_time}
        {event.docente ? ` · ${event.docente}` : ''}
      </div>

      {/* Riga con pulsanti di stato e nota */}
      <div className="flex items-center gap-1 border-t pt-2">
        {(['seguire', 'seguita', 'nonseguita', 'saltare', 'annullata'] as const).map(
          (s) => {
            const active = event.status === s
            const disabled = isRecorded && s !== 'seguita'
            const Icon =
              s === 'seguita'
                ? Check
                : s === 'nonseguita'
                  ? AlertCircle
                  : s === 'saltare'
                    ? SkipForward
                    : s === 'annullata'
                      ? Ban
                      : Clock
            return (
              <IconButton
                key={s}
                label={STATUS_LABELS[s]}
                icon={Icon}
                side="top"
                active={active}
                unavailable={disabled ? 'Ora già registrata' : undefined}
                className={active ? 'bg-primary text-primary-foreground' : undefined}
                onClick={() => {
                  if (!disabled) onStatusChange(s)
                }}
              />
            )
          },
        )}
        <div className="flex-1" />
        <IconButton
          label="Note"
          icon={FileText}
          side="top"
          active={editingNote || !!event.note}
          onClick={() => setEditingNote((prev) => !prev)}
        />
      </div>

      {/* Editor della nota */}
      {editingNote && (
        <div className="flex flex-col gap-1.5 rounded-md bg-muted/50 p-2">
          <textarea
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder="Aggiungi una nota per quest'ora…"
            rows={2}
            className="w-full resize-none rounded border bg-background p-1.5 text-xs outline-none focus:ring-1 focus:ring-primary"
          />
          <div className="flex justify-end gap-0.5">
            <IconButton
              label="Chiudi"
              icon={X}
              side="top"
              onClick={() => setEditingNote(false)}
            />
            <IconButton
              label="Salva la nota"
              icon={Check}
              side="top"
              onClick={() => {
                onNoteSave(noteText)
                setEditingNote(false)
              }}
            />
          </div>
        </div>
      )}

      {/* Sezione Lezione collegata */}
      <div className="flex items-center gap-2 border-t pt-2 text-xs">
        {event.lesson ? (
          <>
            {event.lesson.units_total > 0 ? (
              <span className="font-mono text-xs font-semibold text-study-learned shrink-0">
                {event.lesson.units_learned}/{event.lesson.units_total}
              </span>
            ) : (
              <Mic className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="min-w-0 flex-1 truncate font-medium">
              {event.lesson.titolo || event.lesson.materia}
            </span>
            {event.lesson.units_total > 0 && (
              <Tooltip content="Studia" side="top">
                {(t) => (
                  <Link
                    to={`/studio/lezione/${event.lesson!.id}`}
                    className="inline-flex size-7 items-center justify-center rounded hover:bg-muted"
                    aria-label="Studia"
                    {...t}
                  >
                    <GraduationCap className="size-4" aria-hidden />
                  </Link>
                )}
              </Tooltip>
            )}
            <Tooltip content="Apri lezione" side="top">
              {(t) => (
                <Link
                  to={`/lezioni/${event.lesson!.id}`}
                  className="inline-flex size-7 items-center justify-center rounded hover:bg-muted"
                  aria-label="Apri lezione"
                  {...t}
                >
                  <ExternalLink className="size-4" aria-hidden />
                </Link>
              )}
            </Tooltip>
            <Tooltip content="Scollega lezione" side="top">
              {(t) => (
                <button
                  type="button"
                  className="inline-flex size-7 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-danger"
                  aria-label="Scollega lezione"
                  onClick={() => onLinkLesson(null)}
                  {...t}
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </Tooltip>
          </>
        ) : (
          <>
            <span className="flex-1 text-muted-foreground">Nessuna registrazione</span>
            <IconButton
              label="Collega una lezione"
              icon={LinkIcon}
              side="top"
              active={linking}
              onClick={() => setLinking((prev) => !prev)}
            />
          </>
        )}
      </div>

      {/* Scegli lezione da collegare */}
      {linking && !isRecorded && (
        <div className="flex max-h-40 flex-col gap-1 overflow-auto rounded border bg-muted/40 p-1.5 text-xs">
          <span className="font-semibold text-muted-foreground">Seleziona una lezione:</span>
          {lessonsQuery.data?.map((l) => (
            <button
              key={l.id}
              type="button"
              className="flex items-center justify-between rounded p-1 text-left hover:bg-background"
              onClick={() => {
                onLinkLesson(l.id)
                setLinking(false)
              }}
            >
              <span className="truncate">{l.titolo || l.materia || l.folder_name}</span>
              <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{l.data}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 2. Popup Giorno Intero (Menu del giorno)
// ---------------------------------------------------------------------------

export function DayMenuPopup({
  day,
  anchor,
  onClose,
  onSetDayState,
}: {
  day: CalendarDayView
  anchor: PopupAnchor
  onClose: () => void
  onSetDayState: (status: string) => void
}) {
  const popupRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    function onPointerDown(e: PointerEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [onClose])

  const style = computePopupStyle(anchor, 220)

  return (
    <div
      ref={popupRef}
      style={style}
      role="dialog"
      data-testid="calendar-day-menu"
      aria-label={`Menu giorno ${day.day_name} ${day.day_number}`}
      className="flex flex-col gap-2 rounded-xl border bg-background p-3 text-xs shadow-xl"
    >
      <div className="font-semibold uppercase tracking-wider text-muted-foreground">
        {day.day_name} {day.day_number} {day.month_name} · tutto il giorno
      </div>
      <div className="flex items-center justify-around gap-1 pt-1">
        <IconButton
          label="Non seguita"
          icon={AlertCircle}
          side="top"
          active={day.status === 'nonseguita'}
          onClick={() => {
            onSetDayState('nonseguita')
            onClose()
          }}
        />
        <IconButton
          label="Da saltare"
          icon={SkipForward}
          side="top"
          active={day.status === 'saltare'}
          onClick={() => {
            onSetDayState('saltare')
            onClose()
          }}
        />
        <IconButton
          label="Annullata"
          icon={Ban}
          side="top"
          active={day.status === 'annullata'}
          onClick={() => {
            onSetDayState('annullata')
            onClose()
          }}
        />
        <IconButton
          label="Come da orario"
          icon={Clock}
          side="top"
          active={!day.status}
          onClick={() => {
            onSetDayState('')
            onClose()
          }}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 3. Popup Riepilogo della Settimana (ⓘ)
// ---------------------------------------------------------------------------

export function WeekInfoPopup({
  weekLabel,
  weekNumber,
  summary,
  anchor,
  onClose,
}: {
  weekLabel: string
  weekNumber: string
  summary: CalendarWeekSummary
  anchor: PopupAnchor
  onClose: () => void
}) {
  const popupRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    function onPointerDown(e: PointerEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [onClose])

  const style = computePopupStyle(anchor, 270)

  return (
    <div
      ref={popupRef}
      style={style}
      role="dialog"
      data-testid="calendar-week-popup"
      aria-label="Riepilogo della settimana"
      className="flex flex-col gap-2.5 rounded-xl border bg-background p-3 text-xs shadow-xl"
    >
      <div className="font-semibold uppercase tracking-wider text-muted-foreground">
        Settimana {weekNumber} · {weekLabel}
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <span className="text-muted-foreground">Ore</span>
        <b className="font-mono">{summary.hours_total}</b>

        <span className="text-muted-foreground">Registrate</span>
        <b className="font-mono">{summary.recorded_count}</b>

        <span className="text-muted-foreground">Da saltare</span>
        <b className="font-mono">{summary.skip_count}</b>

        <span className="text-muted-foreground">Settimana tipo</span>
        <b>
          {summary.modified_hours_count > 0
            ? `${summary.modified_hours_count} ore diverse`
            : 'uguale'}
        </b>
      </div>

      {(summary.to_recover ?? []).length > 0 && (
        <div className="flex flex-col gap-1.5 border-t pt-2">
          <div className="font-semibold uppercase tracking-wider text-muted-foreground">
            Da recuperare
          </div>
          <div className="flex max-h-36 flex-col gap-1 overflow-auto">
            {(summary.to_recover ?? []).map((item) => (
              <div key={item.key} className="flex items-center gap-2">
                <span
                  className="size-2 shrink-0 rounded-xs"
                  style={{ backgroundColor: getSubjectColor(item.materia) }}
                  aria-hidden
                />
                <span className="truncate">{item.materia}</span>

                <span className="ml-auto font-mono text-muted-foreground">
                  {item.day_name} {item.day_number}/{item.month_number}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 4. Popup Aggiungi Evento (in modalità modifica)
// ---------------------------------------------------------------------------

export type EventFormValues = {
  materia: string
  startTime: string
  endTime: string
  docente?: string
}

/**
 * Aggiunge un'ora o, con `initial`, modifica quella esistente: stessi campi, precompilati, e
 * Salva al posto di Aggiungi.
 */
export function AddEventPopup({
  scope,
  weekNumber,
  defaultStartTime = '09:00',
  initial,
  anchor,
  onClose,
  onAdd,
}: {
  scope: 'week' | 'tpl'
  weekNumber: string
  defaultStartTime?: string
  initial?: EventFormValues
  anchor: PopupAnchor
  onClose: () => void
  onAdd: (data: EventFormValues) => void
}) {
  const isEdit = !!initial
  const [materia, setMateria] = useState(initial?.materia ?? '')
  const [startTime, setStartTime] = useState(initial?.startTime ?? defaultStartTime)
  const defaultEndTime = () => {
    if (initial) return initial.endTime
    const parts = defaultStartTime.split(':')
    const h = (parseInt(parts[0] || '9', 10) + 2) % 24
    return `${String(h).padStart(2, '0')}:${parts[1] || '00'}`
  }
  const [endTime, setEndTime] = useState(defaultEndTime)
  const [docente, setDocente] = useState(initial?.docente ?? '')
  const popupRef = useRef<HTMLDivElement>(null)
  // Le materie delle lezioni come suggerimenti: il collegamento automatico confronta la materia.
  const lessonsQuery = useLessons()
  const subjectsQuery = useSubjects()
  const knownSubjects = subjectsQuery.data
    ? subjectsQuery.data.map((s) => s.nome)
    : [
        ...new Set((lessonsQuery.data ?? []).map((l) => l.materia).filter((m): m is string => !!m)),
      ].sort()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    function onPointerDown(e: PointerEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [onClose])

  const style = computePopupStyle(anchor, 260)

  return (
    <div
      ref={popupRef}
      style={style}
      role="dialog"
      data-testid={isEdit ? 'calendar-edit-event-popup' : 'calendar-add-event-popup'}
      aria-label={isEdit ? 'Modifica ora' : 'Aggiungi ora'}
      className="flex flex-col gap-2.5 rounded-xl border bg-background p-3 text-xs shadow-xl"
    >
      <div className="font-semibold uppercase tracking-wider text-muted-foreground">
        {isEdit ? 'Modifica ora · ' : ''}
        {scope === 'week' ? `Solo settimana ${weekNumber}` : 'Settimana tipo, da qui in poi'}
      </div>

      <div className="flex flex-col gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Materia</span>
          <input
            type="text"
            value={materia}
            onChange={(e) => setMateria(e.target.value)}
            placeholder="Nome materia"
            list="calendar-known-subjects"
            className="rounded border bg-background px-2 py-1 outline-none focus:ring-1 focus:ring-primary"
            autoFocus
          />
          <datalist id="calendar-known-subjects">
            {knownSubjects.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Inizio</span>
            <input
              type="text"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="rounded border bg-background px-2 py-1 font-mono outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Fine</span>
            <input
              type="text"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="rounded border bg-background px-2 py-1 font-mono outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Docente</span>
          <input
            type="text"
            value={docente}
            onChange={(e) => setDocente(e.target.value)}
            placeholder="Facoltativo"
            className="rounded border bg-background px-2 py-1 outline-none focus:ring-1 focus:ring-primary"
          />
        </label>
      </div>

      <div className="flex justify-end gap-1 pt-1">
        <IconButton label="Annulla" icon={X} side="top" onClick={onClose} />
        <IconButton
          label={isEdit ? 'Salva' : 'Aggiungi'}
          icon={Check}
          side="top"
          className="bg-primary text-primary-foreground hover:opacity-90"
          onClick={() => {
            if (materia.trim()) {
              onAdd({
                materia: materia.trim(),
                startTime,
                endTime,
                docente: docente.trim() || undefined,
              })
              onClose()
            }
          }}
        />
      </div>
    </div>
  )
}
