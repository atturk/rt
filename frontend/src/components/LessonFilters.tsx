import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { STATE_LABELS, type Lesson } from '@/lib/format'
import type { LessonListFilters } from '@/lib/lessonSearch'

/**
 * Barra di ricerca degli elenchi di lezioni (dashboard, Recall, Immagini, Review): testo,
 * materia e stato. Le materie vengono dall'elenco completo già caricato.
 */
export function LessonFilters({
  lessons,
  filters,
  onChange,
  idPrefix = 'filter',
}: {
  lessons: Lesson[]
  filters: LessonListFilters
  onChange: (key: keyof LessonListFilters, value: string) => void
  idPrefix?: string
}) {
  const subjects = [...new Set(lessons.map((l) => l.materia).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'it'))
  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-3" role="search" aria-label="Filtra le lezioni" onSubmit={(e) => e.preventDefault()}>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-q`}>Cerca</Label>
        <Input
          id={`${idPrefix}-q`}
          type="search"
          placeholder="Titolo, materia, data…"
          value={filters.q}
          onChange={(e) => onChange('q', e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-materia`}>Materia</Label>
        <Select id={`${idPrefix}-materia`} value={filters.materia} onChange={(e) => onChange('materia', e.target.value)}>
          <option value="">Tutte</option>
          {subjects.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-stato`}>Stato</Label>
        <Select id={`${idPrefix}-stato`} value={filters.state} onChange={(e) => onChange('state', e.target.value)}>
          <option value="">Tutti</option>
          {Object.entries(STATE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>
    </form>
  )
}
