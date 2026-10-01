import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useRelevance, useRunClassifier } from '@/api/relevance'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RUN_NEW, classificationLabel, statusFromSummary } from '@/lib/classification'

/**
 * Avviso del classificatore: sulla lezione si vede solo se manca qualcosa (mai eseguito, da
 * rifare, solo su alcune unità), con il pulsante per eseguirlo; nella pagina del recall della
 * lezione ("compact") c'è sempre una riga di stato con la scorciatoia.
 */
export function ClassificationNotice({ lessonId, compact = false }: { lessonId: number; compact?: boolean }) {
  const relevance = useRelevance(lessonId)
  const run = useRunClassifier(lessonId)
  if (!relevance.data) return null
  const status = statusFromSummary(relevance.data.mode, relevance.data.summary, relevance.data.units.length)
  if (status.state === 'unavailable' || (status.state === 'disabled' && !compact)) return null
  const label = classificationLabel(status)
  const page = `/lezioni/${lessonId}/rilevanza`
  const runButton = status.state !== 'disabled' && (
    <Button size="sm" variant={label.pending ? 'default' : 'outline'} disabled={run.busy} title={RUN_NEW.title}
      onClick={() => run.start.mutate(false)}>
      {status.state === 'never' ? RUN_NEW.first : label.pending ? RUN_NEW.label : 'Ricontrolla le unità modificate'}
    </Button>
  )
  const progress = (
    <>
      {run.start.isError && <Alert tone="danger">{errorMessage(run.start.error)}</Alert>}
      {run.jobId && <JobProgress jobId={run.jobId} label="Etichette del classificatore" onFinished={run.finished} />}
    </>
  )
  if (compact) {
    return (
      <div className="flex flex-col gap-2" data-testid="classification-notice" data-state={status.state}>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">Classificatore</span>
          <Badge tone={label.tone}>{label.text}</Badge>
          {label.pending && <span className="text-xs text-muted-foreground">il recaller non sa ancora quali unità hanno poco contenuto</span>}
          <span className="ml-auto flex flex-wrap items-center gap-2">
            {runButton}
            <Link to={page} className="text-xs underline-offset-4 hover:underline">Apri il classificatore</Link>
          </span>
        </div>
        {progress}
      </div>
    )
  }
  if (!label.pending && !run.jobId) return null
  const why = status.state === 'never'
    ? 'Il classificatore non è ancora passato su questa lezione.'
    : status.state === 'stale'
      ? 'Le etichette del classificatore sono da rifare: il testo delle unità o la configurazione sono cambiati.'
      : `Il classificatore è passato solo su ${status.classified} unità su ${status.total}.`
  return (
    <Alert tone="warning" className="flex flex-col gap-2" data-testid="classification-notice" data-state={status.state}>
      <span>
        <strong>{why}</strong> Senza le sue etichette il recall non sa quali unità hanno poco contenuto.
      </span>
      <span className="flex flex-wrap items-center gap-3">
        {runButton}
        <Link to={page} className="font-semibold underline">Apri il classificatore</Link>
      </span>
      {progress}
    </Alert>
  )
}
