import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { LessonBrowser } from '@/components/LessonBrowser'
import { Alert } from '@/components/ui/alert'
import { lessonTitle, type Lesson } from '@/lib/format'

function ReviewCard({ lesson }: { lesson: Lesson }) {
  return (
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
  )
}

/** Elenco delle lezioni con issue della review da valutare; la revisione vera è in review.tsx. */
export function ReviewsPage() {
  const lessons = useLessons()
  const toReview = (lessons.data ?? []).filter((l) => l.pending_issues > 0)
  const total = toReview.reduce((sum, l) => sum + l.pending_issues, 0)
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">Review</h1>
      <p className="text-sm text-muted-foreground">
        Le lezioni con issue della revisione scientifica da valutare. Con l'ultima decisione la pipeline in attesa riparte da
        sola.
      </p>
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {lessons.data && (
        <p className="text-xs text-muted-foreground" data-testid="reviews-total">
          {toReview.length === 0
            ? 'Nessuna lezione ha issue da valutare.'
            : `${total} issue da valutare in ${toReview.length} ${toReview.length === 1 ? 'lezione' : 'lezioni'}.`}
        </p>
      )}
      <LessonBrowser
        storageKey="rt-review-view"
        lessons={toReview}
        card={(lesson) => <ReviewCard lesson={lesson} />}
        link={(lesson) => `/lezioni/${lesson.id}/revisione`}
        columns={[{ label: 'Da valutare', className: 'text-right tabular-nums', cell: (lesson) => <span data-testid="review-count">{lesson.pending_issues}</span> }]}
        extraSort={{ label: 'Issue da valutare', dir: 'desc', value: (lesson) => lesson.pending_issues }}
        testId="review-lesson"
        emptyText="Nessuna lezione corrisponde ai filtri."
      />
    </section>
  )
}
