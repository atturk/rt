import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { Schemas } from '@/api/client'
import { LessonJobBanner } from '@/components/jobs/JobsIndicator'
import { Alert } from '@/components/ui/alert'
import { STATE_LABELS, formatCost } from '@/lib/format'
import { CostPanel } from '../CostPanel'
import { JobsPanel } from '../JobsPanel'
import { PhasePanel } from '../PhasePanel'

type Section = Schemas['DocumentSection']

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="self-center text-meta text-muted-foreground">{label}</dt>
      <dd className="[overflow-wrap:anywhere]">{children}</dd>
    </>
  )
}

const panelLink = 'font-semibold text-link underline-offset-2 hover:underline'

export function DetailsPanel({ lesson: l, sections, editingDocument }: { lesson: Schemas['LessonDetail']; sections: Section[]; editingDocument: boolean }) {
  const actions = l.actions
  return (
    <div className="flex flex-col gap-4 text-body">
      <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2" data-testid="lesson-details">
        <Row label="Stato">{l.state ? STATE_LABELS[l.state] ?? l.state : '—'}</Row>
        <Row label="Segmenti">{l.segment_count}</Row>
        <Row label="Issue da valutare">{l.pending_issues}</Row>
        <Row label="Costo"><span className="tabular-nums">{formatCost(l.cost_usd)}</span></Row>
      </dl>
      {l.error && <Alert tone="danger">{l.error}</Alert>}
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-meta" data-testid="lesson-links">
        {actions?.recall.available ? <Link to={`/lezioni/${l.id}/recall`} className={panelLink}>Recall</Link> : null}
        {actions?.images.available ? <Link to={`/lezioni/${l.id}/arricchimento`} className={panelLink}>Arricchimento</Link> : null}
      </p>
      <LessonJobBanner lessonId={l.id} waiting={false} review={Boolean(l.phases.review && l.phases.review !== 'MISSING')} />
      <PhasePanel lessonId={l.id} units={sections} editingDocument={editingDocument} />
      <JobsPanel lessonId={l.id} />
      <CostPanel lesson={l} />
    </div>
  )
}

