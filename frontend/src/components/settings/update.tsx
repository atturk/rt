import { useEffect, useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/jobs'
import { SettingsGroup, SettingsSwitch } from './ui'
import { useAppUpdate, useReloadWhenUpdated, useUpdateNotice, type AppUpdate } from './useAppUpdate'

const BUSY = new Set(['downloading', 'verifying', 'installing'])

export function UpdateSection() {
  const { data, phase, percent, update, refresh, download, install, setChannel } = useAppUpdate()
  const { notice, seenKey, markSeen } = useUpdateNotice()
  const [stalledAt99, setStalledAt99] = useState(false)
  const markedRef = useRef<string | null>(null)

  useEffect(() => {
    if (!notice) {
      markedRef.current = null
      return
    }
    if (seenKey && markedRef.current !== seenKey) {
      markedRef.current = seenKey
      markSeen()
    }
  }, [notice, seenKey, markSeen])

  const isAt99 = phase === 'downloading' && percent !== null && percent >= 99
  useEffect(() => {
    if (!isAt99) return
    const timer = setTimeout(() => setStalledAt99(true), 2000)
    return () => {
      clearTimeout(timer)
      setStalledAt99(false)
    }
  }, [isAt99])

  useReloadWhenUpdated(phase === 'installing' ? data?.progress?.target ?? null : null)
  if (update.isError && !update.data) {
    return (
      <SettingsGroup id="aggiornamenti" title="Aggiornamenti">
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(update.error)}</Alert>
        </div>
      </SettingsGroup>
    )
  }
  if (!data?.current) return null

  const channelLabel = data.channel === 'beta' ? 'beta' : 'stabile'
  const isReady = data.ready || phase === 'ready'
  const isInstalling = phase === 'installing' || install.isPending

  return (
    <SettingsGroup id="aggiornamenti" title="Aggiornamenti" description={`Canale: ${channelLabel}`}>
      <div className="divide-y divide-border/60 text-body" data-testid="app-update">
        <SettingsSwitch
          id="beta-switch"
          label="Beta"
          info="Ricevi anche le versioni di prova prima del rilascio stabile."
          checked={data.channel === 'beta'}
          disabled={setChannel.isPending}
          onChange={(val) => setChannel.mutate(val ? 'beta' : 'stable')}
        />
        <div className="flex flex-col gap-3 px-4 py-3">
          {(phase === 'verifying' || stalledAt99) && !isInstalling && <p role="status">Verifico il pacchetto…</p>}
          {phase === 'downloading' && !stalledAt99 && !isInstalling && (
            <div className="space-y-2">
              <div className="flex max-w-sm items-baseline justify-between gap-2 text-body">
                <span role="status">Scarico RT {data.progress.target}…</span>
                {(percent !== null || data.progress.downloaded > 0) && (
                  <span className="text-meta tabular-nums text-muted-foreground">
                    {percent !== null ? `${percent}%` : ''}
                    {percent !== null && data.progress.total ? ' · ' : ''}
                    {data.progress.total
                      ? `${formatBytes(data.progress.downloaded)} / ${formatBytes(data.progress.total)}`
                      : data.progress.downloaded > 0
                        ? formatBytes(data.progress.downloaded)
                        : ''}
                  </span>
                )}
              </div>
              <progress
                className="h-2 w-full max-w-sm accent-primary"
                value={percent ?? 0}
                max={100}
                role="progressbar"
                aria-label="Avanzamento download"
              />
              <p className="text-meta text-muted-foreground">
                Download avviato: puoi continuare a usare RT. Quando finisce, o se qualcosa va storto, lo vedi qui e sull'icona delle Impostazioni.
              </p>
            </div>
          )}
          {isInstalling && <p role="status">Riavvio in corso…</p>}
          {phase === 'error' && !isInstalling && <Alert tone="danger">{data.progress.error}</Alert>}
          {!BUSY.has(phase ?? '') && !install.isPending && <UpdateStatus data={data} isReady={isReady} />}
          {download.isError && <Alert tone="danger">{errorMessage(download.error)}</Alert>}
          {install.isError && <Alert tone="danger">{errorMessage(install.error)}</Alert>}

          <div className="flex flex-wrap items-center gap-3">
            {data.supported && (isReady || isInstalling) && phase !== 'downloading' && phase !== 'verifying' && (
              <Button disabled={isInstalling} onClick={() => install.mutate()}>
                Installa e riavvia
              </Button>
            )}
            {data.supported && data.available && !isReady && !BUSY.has(phase ?? '') && !install.isPending && (
              <Button disabled={download.isPending} onClick={() => download.mutate()}>
                Scarica{data.asset_size ? ` (${formatBytes(data.asset_size)})` : ''}
              </Button>
            )}
            {!BUSY.has(phase ?? '') && !install.isPending && (
              <Button variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate()}>Controlla ora</Button>
            )}
            <a className="text-meta underline" href={data.releases_url} target="_blank" rel="noreferrer">Pagina delle release</a>
          </div>
        </div>
      </div>
    </SettingsGroup>
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
