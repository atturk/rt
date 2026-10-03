import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { Link } from 'react-router'

import { errorMessage, type Schemas } from '@/api/client'
import { useRunJob } from '@/api/hooks'
import { LessonJobBanner } from '@/components/jobs/JobsIndicator'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { STATE_LABELS, formatCost } from '@/lib/format'
import { CostPanel } from './CostPanel'
import { JobsPanel } from './JobsPanel'
import { PhasePanel } from './PhasePanel'
import { PANEL_ID, type PanelView } from '@/lib/lessonPanel'

type Section = Schemas['DocumentSection']

const TITLES: Record<PanelView, string> = { dettagli: 'Dettagli', verifica: 'Verifica con LLM' }

/**
 * Pannello laterale della lezione (design 4.2: "Verifica e Dettagli si aprono come pannelli
 * laterali"): quello che prima stava nella pagina (fasi, scaletta, rilevanza, job, costi,
 * revisione) resta raggiungibile da qui, il documento sta davanti.
 */
export function LessonPanel({ view, lesson, sections, editingDocument, onClose }: {
  view: PanelView
  lesson: Schemas['LessonDetail']
  sections: Section[]
  editingDocument: boolean
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]')) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <aside
      id={PANEL_ID}
      aria-label={TITLES[view]}
      data-testid="lesson-panel"
      data-view={view}
      className="fixed bottom-0 right-0 top-(--header-height) z-10 flex w-[min(24rem,100vw)] flex-col overflow-y-auto border-l bg-background px-4 pb-6 pt-3 shadow-panel max-md:top-0 max-md:z-40 max-md:pb-[calc(80px+env(safe-area-inset-bottom))]"
    >
      <div className="mb-3 flex items-center gap-2">
        <h2 className="min-w-0 flex-1 text-[15px] font-semibold">{TITLES[view]}</h2>
        <IconButton label="Chiudi il pannello" icon={X} onClick={onClose} className="-mr-2" />
      </div>
      {view === 'dettagli' ? <Details lesson={lesson} sections={sections} editingDocument={editingDocument} /> : <Review lesson={lesson} />}
    </aside>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="self-center text-meta text-muted-foreground">{label}</dt>
      <dd className="[overflow-wrap:anywhere]">{children}</dd>
    </>
  )
}

const panelLink = 'font-semibold text-link underline-offset-2 hover:underline'

function Details({ lesson: l, sections, editingDocument }: { lesson: Schemas['LessonDetail']; sections: Section[]; editingDocument: boolean }) {
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

function Review({ lesson: l }: { lesson: Schemas['LessonDetail'] }) {
  const run = useRunJob(l.id)
  const done = Boolean(l.phases.review && l.phases.review !== 'MISSING')
  const ready = l.phases.rewrite === 'VALID'
  return (
    <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
      <p>
        {done
          ? l.pending_issues > 0
            ? `${l.pending_issues === 1 ? 'Una issue' : `${l.pending_issues} issue`} da valutare.`
            : 'Nessuna issue da valutare.'
          : 'La lezione non è ancora stata verificata.'}
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
      {run.isSuccess && <p role="status" className="text-meta text-muted-foreground">Verifica avviata: l'avanzamento è in cima alla pagina.</p>}
      {run.isError && <Alert tone="danger">{errorMessage(run.error)}</Alert>}
      <p className="text-meta text-muted-foreground">Per verificare solo una parte: seleziona il testo (o fai clic destro su un titolo) e scegli Verifica questa parte.</p>
    </div>
  )
}
