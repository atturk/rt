import { Link } from 'react-router'
import { errorMessage, type Schemas } from '@/api/client'
import { useRunJob } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

const panelLink = 'font-semibold text-link underline-offset-2 hover:underline'

export function ReviewPanel({ lesson: l }: { lesson: Schemas['LessonDetail'] }) {
  const run = useRunJob(l.id)
  const done = Boolean(l.phases.review && l.phases.review !== 'MISSING')
  const ready = l.phases.rewrite === 'VALID'
  return (
    <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
      <p>
        {done
          ? l.pending_issues > 0
            ? `${l.pending_issues === 1 ? '1 issue' : `${l.pending_issues} issue`} da valutare`
            : '0 issue da valutare'
          : 'Mai verificata'}
      </p>
      {done && (
        <Link to={`/lezioni/${l.id}/revisione`} className={panelLink}>
          {l.pending_issues > 0 ? 'Rivedi le decisioni' : 'Apri la revisione'}
        </Link>
      )}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        disabled={!ready || run.isPending}
        title={ready ? undefined : 'Serve prima la rielaborazione della lezione'}
        onClick={() => run.mutate({ type: 'run_phase', phase: 'review', force: done })}
      >
        {done ? 'Verifica di nuovo tutta la lezione' : 'Verifica tutta la lezione'}
      </Button>
      {run.isSuccess && <p role="status" className="text-meta text-muted-foreground">Verifica avviata</p>}
      {run.isError && <Alert tone="danger">{errorMessage(run.error)}</Alert>}
    </div>
  )
}
