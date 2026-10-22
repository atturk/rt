import { useEffect } from 'react'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/jobs'
import { useAppUpdate, useReloadWhenUpdated } from './useAppUpdate'

export function UpdatePopup() {
  const { data, phase, percent, refresh, download, install } = useAppUpdate()
  // mutate è stabile, l'oggetto della mutation no: con [refresh] il controllo ripartiva a ogni
  // render e GitHub rispondeva 429.
  const { mutate: checkNow } = refresh

  useEffect(() => {
    checkNow()
  }, [checkNow])

  useReloadWhenUpdated(phase === 'installing' ? data?.progress?.target ?? null : null)

  if (!data) {
    return <div className="p-4 text-sm text-muted-foreground">Controllo aggiornamenti…</div>
  }

  const version = data.latest || data.current
  const isPrerelease = data.prerelease
  const notesUrl = data.notes_url
  const isReady = data.ready || phase === 'ready'
  const isDownloading = phase === 'downloading'
  const isInstalling = phase === 'installing'
  const isError = phase === 'error' || download.isError || install.isError
  const errorMessageText =
    data.progress?.error ||
    (download.isError && 'Download non riuscito.') ||
    (install.isError && 'Installazione non riuscita.') ||
    'Errore di aggiornamento.'

  return (
    <div className="flex h-full min-h-[190px] flex-col justify-between p-4" data-testid="update-popup">
      {/* Riga 1: RT <versione>, con badge beta se prerelease, e link novità */}
      <div className="flex items-center gap-2 text-base font-semibold">
        <span>RT {version}</span>
        {isPrerelease && <Badge tone="warning">beta</Badge>}
        {notesUrl && (
          <a
            href={notesUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-normal text-muted-foreground underline hover:text-foreground"
          >
            novità
          </a>
        )}
      </div>

      {/* Stato */}
      <div className="my-auto py-2">
        {isInstalling ? (
          <p role="status" className="text-sm">
            Installo RT {data.progress.target || version}…
          </p>
        ) : isDownloading ? (
          <div className="space-y-2">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Scarico RT {data.progress.target || version}…</span>
              {percent !== null && <span>{percent}%</span>}
            </div>
            <progress
              className="h-2 w-full accent-primary"
              value={percent ?? 0}
              max={100}
              role="progressbar"
              aria-label="Avanzamento download"
            />
          </div>
        ) : isError ? (
          <div className="space-y-3">
            <Alert tone="danger">{errorMessageText}</Alert>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (isReady) install.mutate()
                else download.mutate()
              }}
            >
              Riprova
            </Button>
          </div>
        ) : isReady ? (
          <Button
            className="w-full"
            disabled={install.isPending}
            onClick={() => install.mutate()}
          >
            Installa e riavvia
          </Button>
        ) : data.available ? (
          <Button
            className="w-full"
            disabled={download.isPending}
            onClick={() => download.mutate()}
          >
            Scarica{data.asset_size ? ` (${formatBytes(data.asset_size)})` : ''}
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">RT è aggiornato.</p>
        )}
      </div>
    </div>
  )
}
