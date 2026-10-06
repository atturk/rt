import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { errorMessage } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { recallKeys, useGenerateRecall, useStudyLesson, type RecallGenerateType, type RecallType } from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { QUESTION_TYPE_LABELS } from '@/lib/questionTypes'

/** La sessione usa le domande nuove appena il job le ha salvate. */
export function EmptyGeneration({ lessonId, unit, available = true, onGenerated }: {
  lessonId: number
  available?: boolean
  unit?: { id: string; suggestions?: boolean; suggestedQtype?: RecallType | null }
  onGenerated: () => void
}) {
  const study = useStudyLesson(unit?.suggestions !== undefined ? null : lessonId)
  const suggestions = unit?.suggestions ?? study.data?.suggestions ?? false
  const generate = useGenerateRecall(lessonId)
  const client = useQueryClient()
  const [count, setCount] = useState(unit ? '3' : '10')
  const [customType, setCustomType] = useState<RecallType>('quiz')
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const running = !!jobId && !jobFinished(job.data)
  const start = (qtype: RecallGenerateType) => generate.mutate({
    qtype, count: Math.min(20, Math.max(1, parseInt(count, 10) || (unit ? 3 : 10))),
    ...(unit ? { unit_ids: [unit.id] } : {}),
  }, { onSuccess: accepted => setJobId(accepted.job_id) })
  if (!suggestions || (!available && !jobId)) return null
  return <div className="mt-4 text-left" data-testid="recall-empty-generation">
    {jobId && <JobProgress jobId={jobId} label="Genero le domande…" onFinished={state => {
      if (state !== 'succeeded') return
      void client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }).then(() => {
        setJobId(null)
        onGenerated()
      })
    }} />}
    {!running && <div className="rt-empty-generation flex flex-wrap items-center justify-center gap-2">
      <label htmlFor="empty-gen-count" className="text-meta text-muted-foreground">Quante</label>
      <Input id="empty-gen-count" type="number" min="1" max="20" value={count} onChange={e => setCount(e.target.value)} className="h-9 w-16 text-center" />
      <Button disabled={generate.isPending} onClick={() => start('consigliato')} className="rt-empty-advised">
        <Sparkles className="size-3.5" aria-hidden />Genera consigliato{unit?.suggestedQtype ? ` · ${QUESTION_TYPE_LABELS[unit.suggestedQtype]}` : ''}
      </Button>
      <Select aria-label="Tipo di domanda personalizzato" value={customType} onChange={e => setCustomType(e.target.value as RecallType)} className="rt-empty-type w-auto">
        {(Object.keys(QUESTION_TYPE_LABELS) as RecallType[]).filter(type => !unit || type !== 'vasta').map(type => <option key={type} value={type}>{QUESTION_TYPE_LABELS[type]}</option>)}
      </Select>
      <Button variant="outline" disabled={generate.isPending} onClick={() => start(customType)} className="rt-empty-custom">Genera personalizzato</Button>
    </div>}
    {generate.isError && <Alert tone="danger" className="mt-2">{errorMessage(generate.error)}</Alert>}
  </div>
}
