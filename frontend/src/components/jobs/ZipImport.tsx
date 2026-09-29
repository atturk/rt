import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { invalidateAfterJob, useImportLessonZips, type ZipImportResult } from '@/api/jobs'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { JobProgress } from '@/components/JobProgress'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { formatBytes } from '@/lib/jobs'

/**
 * Importazione di lezioni da ZIP completi: l'upload accoda il job import_lesson_zips, che
 * 'rt worker' esegue; l'avanzamento e l'esito per archivio si leggono dal job.
 */
export function ZipImportCard() {
  const client = useQueryClient()
  const [archives, setArchives] = useState<File[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const upload = useImportLessonZips()
  const job = useJobStatus(jobId)
  const result = job.data?.state === 'succeeded' ? (job.data.result as ZipImportResult | null) : null
  const running = upload.isPending || (!!jobId && !job.isError && !jobFinished(job.data))
  // lezioni nuove: elenco e job si rileggono quando il job finisce
  const finished = useCallback(() => invalidateAfterJob(client), [client])
  const progress = upload.progress
  const percent = progress?.total ? Math.round((progress.loaded / progress.total) * 100) : null

  function start() {
    setJobId(null)
    upload.mutate(archives, { onSuccess: (accepted) => setJobId(accepted.job_id) })
  }

  return (
    <Card className="flex flex-col gap-3 p-5">
      <h2 className="text-sm font-bold">Importa lezioni da ZIP completi</h2>
      <p className="text-xs text-muted-foreground">Usa archivi esportati con «Tutti i dati». Una lezione già esistente viene rifiutata senza interrompere le altre.</p>
      <Input type="file" accept=".zip,application/zip" multiple aria-label="Archivi ZIP delle lezioni" disabled={running}
        onChange={(event) => setArchives(Array.from(event.target.files ?? []))} />
      {archives.length > 0 && <span className="text-xs text-muted-foreground">{archives.length} archivi, {formatBytes(archives.reduce((sum, f) => sum + f.size, 0))}.</span>}
      <Button type="button" disabled={!archives.length || running} onClick={start}>{running ? 'Importazione…' : 'Importa ZIP'}</Button>
      {upload.isPending && <ProgressBar value={percent} label="Caricamento degli archivi" />}
      {upload.isError && <Alert tone="danger">{errorMessage(upload.error)}</Alert>}
      {jobId && <JobProgress jobId={jobId} label="Importazione degli archivi" onFinished={finished} />}
      {result && <ul className="text-xs" aria-label="Esito importazione ZIP">{result.results.map((item, index) => <li key={index}>
        {item.file}: {item.status === 'imported'
          ? <>importata{item.lesson_id != null && <> — <Link className="underline" to={`/lezioni/${item.lesson_id}`}>apri</Link></>}</>
          : `rifiutata — ${item.reason}`}
      </li>)}</ul>}
    </Card>
  )
}
