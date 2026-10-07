import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { errorMessage } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { recallKeys, useGenerateRecall, useStudyLesson, type RecallType } from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { QuestionTypeChips } from './QuestionTypeChips'
import { mostSuggested } from '@/lib/questionTypes'

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
  const suggested = suggestions ? unit?.suggestedQtype ?? mostSuggested(study.data?.units ?? []).type : null
  const [chosenType, setCustomType] = useState<RecallType | null>(null)
  const customType = chosenType ?? suggested ?? 'quiz'
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const running = !!jobId && !jobFinished(job.data)
  const start = (qtype: RecallType) => generate.mutate({
    qtype, count: Math.min(20, Math.max(1, parseInt(count, 10) || (unit ? 3 : 10))),
    ...(unit ? { unit_ids: [unit.id] } : {}),
  }, { onSuccess: accepted => setJobId(accepted.job_id) })
  if (!available && !jobId) return null
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
      <QuestionTypeChips value={customType} onChange={setCustomType} suggested={suggested} unit={!!unit} disabled={generate.isPending} />
      <Button disabled={generate.isPending} onClick={() => start(customType)}>Genera</Button>
    </div>}
    {generate.isError && <Alert tone="danger" className="mt-2">{errorMessage(generate.error)}</Alert>}
  </div>
}
