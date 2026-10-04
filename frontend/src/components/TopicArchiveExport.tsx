import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { topicArchiveUrl, useExportTopicArchive, type TopicArchiveResult } from '@/api/telegram'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/jobs'

/**
 * Esportazione di un topic con cronologia e media: job telegram_topic_export eseguito da
 * 'rt worker' (può durare minuti); a job concluso lo ZIP si scarica dal link.
 */
export function TopicArchiveExport({ topic }: { topic: { id: number; name: string } }) {
  const [jobId, setJobId] = useState<string | null>(null)
  const start = useExportTopicArchive()
  const job = useJobStatus(jobId)
  const result = job.data?.state === 'succeeded' ? (job.data.result as TopicArchiveResult | null) : null
  const running = start.isPending || (!!jobId && !job.isError && !jobFinished(job.data))
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold">{topic.name}</span>
        <Button size="sm" variant="outline" disabled={running}
          onClick={() => { setJobId(null); start.mutate(topic.id, { onSuccess: (accepted) => setJobId(accepted.job_id) }) }}>
          {running ? 'Esportazione…' : jobId ? 'Esporta di nuovo' : 'Esporta con cronologia e media'}
        </Button>
      </div>
      {start.isError && <Alert tone="danger">{errorMessage(start.error)}</Alert>}
      {jobId && <JobProgress jobId={jobId} label={`Esportazione di «${topic.name}»`} />}
      {jobId && result && (
        <a className="text-sm font-semibold text-link underline" href={topicArchiveUrl(jobId)} download={result.file}>
          Scarica «{topic.name}» ({result.messages} messaggi, {formatBytes(result.size)}) ↧
        </a>
      )}
    </div>
  )
}
