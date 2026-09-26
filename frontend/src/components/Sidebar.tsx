import { ChevronDown } from 'lucide-react'
import { NavLink } from 'react-router'

import { useLessons } from '@/api/hooks'
import { errorMessage } from '@/api/client'
import { groupBySubject, lessonTitle } from '@/lib/format'
import { cn } from '@/lib/utils'

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const lessons = useLessons()
  return (
    <nav aria-label="Lezioni per materia" className="flex flex-col gap-4 text-sm">
      {lessons.isPending && <p className="px-2 text-xs text-muted-foreground">Carico le lezioni…</p>}
      {lessons.isError && <p className="px-2 text-xs text-danger">{errorMessage(lessons.error)}</p>}
      {lessons.data?.length === 0 && <p className="px-2 text-xs text-muted-foreground">Nessuna lezione.</p>}
      {groupBySubject(lessons.data ?? []).map(([subject, items]) => (
        <details key={subject} open className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between px-1.5 py-1 text-[11px] font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
            {subject}
            <ChevronDown className="size-3.5 -rotate-90 transition-transform group-open:rotate-0" aria-hidden />
          </summary>
          <ul className="mt-1 flex flex-col">
            {items.map((lesson) => (
              <li key={lesson.id}>
                <NavLink
                  to={`/lezioni/${lesson.id}`}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn('flex flex-col gap-0.5 rounded-lg px-2.5 py-2 hover:bg-muted', isActive && 'bg-accent text-accent-foreground')
                  }
                >
                  <span className="text-[11px] text-muted-foreground">{lesson.data || 'Senza data'}</span>
                  <span className="text-xs font-semibold leading-snug">{lessonTitle(lesson)}</span>
                  {lesson.pending_issues > 0 && (
                    <span className="text-[11px] text-accent-foreground">{lesson.pending_issues} da rivedere</span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </nav>
  )
}
