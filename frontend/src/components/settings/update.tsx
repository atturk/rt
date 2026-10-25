import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { formatBytes } from '@/lib/jobs'
import { Section } from './common'
import { useAppUpdate, useReloadWhenUpdated, type AppUpdate } from './useAppUpdate'

const BUSY = new Set(['downloading', 'installing'])

export function UpdateSection() {
  const { data, phase, percent, update, refresh, download, install, setChannel } = useAppUpdate()

  useReloadWhenUpdated(phase === 'installing' ? data?.progress?.target ?? null : null)
  if (update.isError && !update.data) {
    return (
      <Section id="aggiornamenti" title="Aggiornamenti">
        <Alert tone="danger">{errorMessage(update.error)}</Alert>
      </Section>
    )
  }
  if (!data?.current) return null

  const channelLabel = data.channel === 'beta' ? 'beta' : 'stabile'
  const isReady = data.ready || phase === 'ready'

  return (
    <Section id="aggiornamenti" title="Aggiornamenti" description={`Canale: ${channelLabel}`}>
      <div className="space-y-4 text-body" data-testid="app-update">
        <div className="flex items-center gap-2">
          <label htmlFor="beta-switch" className="cursor-pointer text-sm font-medium">Beta</label>
          <Switch
            label="Beta"
            checked={data.channel === 'beta'}
            disabled={setChannel.isPending}
            onChange={(val) => setChannel.mutate(val ? 'beta' : 'stable')}
          />
        </div>

        {phase === 'downloading' && <p role="status">Scarico RT {data.progress.target}{percent !== null ? ` (${percent}%)` : ''}…</p>}
        {phase === 'installing' && (
          <div className="space-y-2">
            <p role="status">Installo RT {data.progress.target}: RT si riavvia e questa pagina si ricarica da sola.</p>
            <progress className="h-2 w-full max-w-sm accent-primary" aria-label="Installazione" />
          </div>
        )}
        {phase === 'error' && <Alert tone="danger">{data.progress.error}</Alert>}
        {!BUSY.has(phase ?? '') && <UpdateStatus data={data} isReady={isReady} />}
        {download.isError && <Alert tone="danger">{errorMessage(download.error)}</Alert>}
        {install.isError && <Alert tone="danger">{errorMessage(install.error)}</Alert>}

        <div className="flex flex-wrap items-center gap-3">
          {data.supported && isReady && !BUSY.has(phase ?? '') && (
            <Button disabled={install.isPending} onClick={() => install.mutate()}>
              Installa e riavvia
            </Button>
          )}
          {data.supported && data.available && !isReady && !BUSY.has(phase ?? '') && (
            <Button disabled={download.isPending} onClick={() => download.mutate()}>
              Scarica{data.asset_size ? ` (${formatBytes(data.asset_size)})` : ''}
            </Button>
          )}
          {!BUSY.has(phase ?? '') && (
            <Button variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate()}>Controlla ora</Button>
          )}
          <a className="text-meta underline" href={data.releases_url} target="_blank" rel="noreferrer">Pagina delle release</a>
        </div>
      </div>
    </Section>
  )
}

function UpdateStatus({ data, isReady }: { data: AppUpdate; isReady?: boolean }) {
  if (data.error) return <p className="text-muted-foreground">{data.error}</p>
  if (isReady) {
    return <p>RT <span className="font-semibold tabular-nums">{data.latest}</span> è pronto per l'installazione.</p>
  }
  if (data.available) {
    return <p>È disponibile RT <span className="font-semibold tabular-nums">{data.latest}</span>
      {data.notes_url && <> · <a className="underline" href={data.notes_url} target="_blank" rel="noreferrer">novità</a></>}.</p>
  }
  if (!data.supported && data.latest && data.latest !== data.current) {
    return <p>Ultima versione: <span className="tabular-nums">{data.latest}</span>.</p>
  }
  return <p className="text-muted-foreground">RT è aggiornato.</p>
}
