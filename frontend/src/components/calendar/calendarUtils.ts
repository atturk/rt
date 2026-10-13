import type { CalendarEventView } from '@/api/calendar'

export const STATUS_LABELS: Record<string, string> = {
  seguire: 'Da seguire',
  seguita: 'Seguita',
  nonseguita: 'Non seguita',
  saltare: 'Da saltare',
  annullata: 'Annullata',
}

export function getEventTooltip(e: CalendarEventView): string {
  const time = `${e.start_time}–${e.end_time}`
  let desc = ''
  if (e.lesson) {
    if (e.lesson.units_total > 0) {
      desc = `Seguita · ${e.lesson.units_learned}/${e.lesson.units_total} unità apprese`
    } else {
      desc = 'Seguita · in rielaborazione'
    }
  } else {
    desc = STATUS_LABELS[e.status] ?? 'Da seguire'
  }
  let out = `${e.materia} · ${time}${e.docente ? ` · ${e.docente}` : ''}\n${desc}`
  if (e.is_modified) {
    out += '\nSolo questa settimana'
  }
  if (e.note) {
    out += `\nNota: ${e.note}`
  }
  return out
}
