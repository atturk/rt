import { CircleHelp } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'
import { STATE_LABELS, type Lesson } from '@/lib/format'
import { SEARCH_HELP, type LessonListFilters } from '@/lib/lessonSearch'

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
        <div className="flex items-center gap-1">
          <Label htmlFor={`${idPrefix}-q`}>Cerca</Label>
          <Tooltip content={SEARCH_HELP}>
            {(props) => (
              <button
                type="button"
                {...props}
                aria-label="Informazioni sul filtro di testo"
                className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
              >
                <CircleHelp className="size-3.5" aria-hidden />
              </button>
            )}
          </Tooltip>
        </div>
        <Input
          id={`${idPrefix}-q`}
          type="search"
          placeholder="Titolo, argomenti, materia o data"
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
