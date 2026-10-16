import { errorMessage } from '@/api/client'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cancelUpload, useUploads } from '@/lib/uploadQueue'

/** Caricamenti della nuova lezione ancora sul browser (IM2): il job nasce a trasferimento finito. */
export function UploadList() {
  const uploads = useUploads()
  if (uploads.length === 0) return null
  return (
    <ul className="flex flex-col gap-2" aria-label="Caricamenti in corso">
      {uploads.map((item) => {
        const percent = item.total ? Math.round((item.loaded / item.total) * 100) : null
        return (
          <li key={item.id}>
            <Card className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3" data-testid="upload-row" data-state={item.state}>
              <span className="font-semibold">Caricamento</span>
              <span className="text-xs text-muted-foreground">{item.label}</span>
              <span className="ml-auto flex items-center gap-2">
                <button type="button" className="text-xs underline" onClick={() => cancelUpload(item.id)}>
                  {item.state === 'failed' ? 'Togli' : 'Annulla'}
                </button>
                <Badge tone={item.state === 'failed' ? 'danger' : item.state === 'queued' ? 'neutral' : 'success'}>
                  {item.state === 'failed' ? 'Non riuscito' : item.state === 'queued' ? 'In coda' : percent != null ? `${percent}%` : 'In corso'}
                </Badge>
              </span>
              <span className="basis-full truncate text-xs text-muted-foreground">{item.files.join(', ')}</span>
              {item.state === 'uploading' && <ProgressBar value={percent} label={`Caricamento di ${item.label}`} className="basis-full h-1.5" />}
              {item.state === 'failed' && <span className="basis-full text-xs text-danger">{errorMessage(item.error)}</span>}
            </Card>
          </li>
        )
      })}
    </ul>
  )
}
