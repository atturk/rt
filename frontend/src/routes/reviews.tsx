import { ClipboardCheck } from 'lucide-react'
import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { LessonFilters } from '@/components/LessonFilters'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { Alert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { lessonTitle } from '@/lib/format'
import type { Area } from './types'

/** Elenco delle lezioni con issue della review da valutare; la revisione vera è in review.tsx. */
export function ReviewsPage() {
  const lessons = useLessons()
  const toReview = (lessons.data ?? []).filter((l) => l.pending_issues > 0)
  const { filters, setFilter, filtered } = useFilteredLessons(toReview)
  const total = toReview.reduce((sum, l) => sum + l.pending_issues, 0)
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">Review</h1>
      <p className="text-sm text-muted-foreground">
        Le lezioni con issue della revisione scientifica da valutare. Con l'ultima decisione la pipeline in attesa riparte da
        sola.
      </p>
      <LessonFilters lessons={toReview} filters={filters} onChange={setFilter} />
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {lessons.data && (
        <p className="text-xs text-muted-foreground" data-testid="reviews-total">
          {toReview.length === 0
            ? 'Nessuna lezione ha issue da valutare.'
            : `${total} issue da valutare in ${toReview.length} ${toReview.length === 1 ? 'lezione' : 'lezioni'}.`}
        </p>
      )}
      {toReview.length > 0 && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">Nessuna lezione corrisponde ai filtri.</Card>
      )}
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {filtered.map((lesson) => (
          <li key={lesson.id}>
            <Link
              to={`/lezioni/${lesson.id}/revisione`}
              data-testid="review-lesson"
              data-lesson-id={lesson.id}
              className="flex items-center gap-3 rounded-xl border bg-card p-4 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
            >
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="font-semibold">{lessonTitle(lesson)}</span>
                <span className="text-xs text-muted-foreground">{[lesson.materia, lesson.data].filter(Boolean).join(' · ')}</span>
              </span>
              <span className="flex shrink-0 flex-col items-end">
                <strong className="text-2xl font-bold tabular-nums text-accent-foreground" data-testid="review-count">
                  {lesson.pending_issues}
                </strong>
                <span className="text-[11px] text-muted-foreground">da valutare</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export const reviewsArea: Area = {
  routes: [{ path: 'review', element: <ReviewsPage /> }],
  nav: [{ to: '/review', label: 'Review', icon: ClipboardCheck }],
}
