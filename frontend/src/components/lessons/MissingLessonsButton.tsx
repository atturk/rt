import { Link } from 'react-router'
import { TriangleAlert } from 'lucide-react'
import { useMissingLessons } from '@/api/calendar'
import { IconButton } from '@/components/ui/icon-button'
import { usePreference } from '@/lib/preferences'
import { useHoverExpand } from '@/lib/useHoverExpand'
import { filterMissingLessons, type LessonsGrouping } from '@/lib/lessonsPage'

export interface MissingLessonsButtonProps {
  grouping?: LessonsGrouping
  groupKey?: string
  materia?: string
}

export function MissingLessonsButton({
  grouping = 'materia',
  groupKey,
  materia,
}: MissingLessonsButtonProps) {
  const [enabled] = usePreference('calendar.missing-warning', true)
  const missing = useMissingLessons(enabled)
  const { open, setOpen, ref } = useHoverExpand<HTMLDivElement>({ openOnHover: false })

  if (!enabled) return null

  const effectiveKey = groupKey ?? materia ?? ''
  const items = filterMissingLessons(missing.data, grouping, effectiveKey)

  if (!items.length) return null

  return (
    <div ref={ref} className="relative inline-flex items-center">
      <IconButton
        icon={TriangleAlert}
        label={`${items.length} lezioni mancanti`}
        aria-expanded={open}
        className="size-5 min-h-5 min-w-5 text-warning [&_svg]:size-3.5"
        onClick={() => setOpen((value) => !value)}
        data-testid="missing-lessons-button"
      />
      {open && (
        <div
          role="region"
          aria-label="Lezioni mancanti"
          data-testid="missing-lessons-popup"
          className="absolute left-0 top-full z-50 mt-1 w-[270px] rounded-lg border border-border bg-card p-2 shadow-panel normal-case tracking-normal"
        >
          <ul className="flex max-h-64 flex-col gap-1.5 overflow-auto text-meta">
            {items.map((item) => (
              <li key={`${item.date}:${item.key}`}>
                <Link
                  className="flex items-center justify-between gap-3 rounded px-1 py-1 text-foreground hover:bg-muted"
                  to={`/calendario?data=${item.date}&evento=${encodeURIComponent(item.key)}`}
                  onClick={() => setOpen(false)}
                >
                  <span>
                    {item.day_name} {item.day_number}/{item.month_number}
                  </span>
                  <span className="font-mono text-muted-foreground">
                    {item.start_time}–{item.end_time}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
