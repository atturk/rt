import type { Schemas } from '@/api/client'

export type Lesson = Schemas['LessonSummary']

export const PHASE_LABELS: Record<string, string> = {
  prepare: 'Preparazione',
  outline: 'Scaletta',
  rewrite: 'Rielaborazione',
  review: 'Revisione',
  build: 'Documento',
}
export const PHASE_ORDER = ['prepare', 'outline', 'rewrite', 'review', 'build']

export const STATE_LABELS: Record<string, string> = {
  metadata_only: 'Solo metadati',
  setup_completato: 'Setup completato',
  preparato: 'Preparata',
  outline_validata: 'Scaletta validata',
  draft_validato: 'Bozza validata',
  revisione_completata: 'Revisione completata',
  in_attesa_revisione_umana: 'Da rivedere',
  pronto_per_build: 'Pronta per il documento',
  completato: 'Completata',
  fallito: 'Fallita',
}

export type Tone = 'success' | 'warning' | 'danger' | 'neutral'

export function phaseTone(status: string | undefined): Tone {
  switch ((status ?? '').toUpperCase()) {
    case 'VALID':
      return 'success'
    case 'PARTIAL':
    case 'STALE':
      return 'warning'
    case 'INVALID':
      return 'danger'
    default:
      return 'neutral'
  }
}

/** Titolo senza la data e la materia usate come prefisso nel nome della cartella (come Gradio). */
export function lessonTitle(lesson: Pick<Lesson, 'titolo' | 'folder_name' | 'materia'>): string {
  let title = (lesson.titolo || lesson.folder_name).replace(/^\[\d{4}-\d{2}-\d{2}\]\s*/, '')
  const prefix = lesson.materia ? `${lesson.materia} - ` : ''
  if (prefix && title.toLocaleLowerCase().startsWith(prefix.toLocaleLowerCase())) title = title.slice(prefix.length)
  return title
}

export function formatCost(value: number | null | undefined): string {
  return `$${(value ?? 0).toFixed(2)}`
}

export function groupBySubject(lessons: Lesson[]): [string, Lesson[]][] {
  const groups = new Map<string, Lesson[]>()
  for (const lesson of lessons) {
    const key = lesson.materia || 'Altre lezioni'
    groups.set(key, [...(groups.get(key) ?? []), lesson])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'it', { sensitivity: 'base' }))
    .map(([subject, items]) => [
      subject,
      [...items].sort((a, b) => (b.data || '').localeCompare(a.data || '') || lessonTitle(b).localeCompare(lessonTitle(a))),
    ])
}

/** Data e ora brevi in italiano ('' se non valida). */
export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
}
