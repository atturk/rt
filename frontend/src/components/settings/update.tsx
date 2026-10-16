import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/jobs'
import { Section } from './common'

type AppUpdate = Schemas['AppUpdate']
const updateKey = ['system', 'update'] as const
const BUSY = new Set(['downloading', 'installing'])

/** Aggiornamenti dell'app installata (RT.app, setup per Windows): solo versioni stabili, con il
 * nuovo installer. Le beta si scaricano a mano dalla pagina delle release. Le installazioni da
 * terminale vedono solo se c'è una versione nuova. */
export function UpdateSection() {
  const client = useQueryClient()
  const update = useQuery({
    queryKey: updateKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/update')),
    refetchInterval: query => query.state.data?.progress?.phase === 'downloading' ? 1000 : false,
  })
  const refresh = useMutation({
    mutationFn: () => unwrap(api.GET('/api/v1/system/update', { params: { query: { refresh: true } } })),
    onSuccess: data => client.setQueryData(updateKey, data),
  })
  const install = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/system/update')),
    onSuccess: data => client.setQueryData(updateKey, data),
  })
  const data = update.data as AppUpdate | undefined
  const phase = data?.progress?.phase
  useReloadWhenUpdated(phase === 'installing' ? data?.progress?.target ?? null : null)
  if (update.isError && !update.data) return <Section id="aggiornamenti" title="Aggiornamenti"><Alert tone="danger">{errorMessage(update.error)}</Alert></Section>
  if (!data?.current) return null
  const percent = data.progress.total ? Math.min(100, Math.round(data.progress.downloaded * 100 / data.progress.total)) : null
  return (
    <Section id="aggiornamenti" title="Aggiornamenti" description="RT si aggiorna solo alle versioni stabili. Le beta si scaricano a mano dalla pagina delle release.">
      <div className="space-y-3 text-body" data-testid="app-update">
        {phase === 'downloading' && <p role="status">Scarico RT {data.progress.target}{percent !== null ? ` (${percent}%)` : ''}…</p>}
        {phase === 'installing' && <p role="status">Installo RT {data.progress.target}: RT si riavvia e questa pagina si ricarica da sola.</p>}
        {phase === 'error' && <Alert tone="danger">{data.progress.error}</Alert>}
        {!BUSY.has(phase ?? '') && <UpdateStatus data={data} />}
        {install.isError && <Alert tone="danger">{errorMessage(install.error)}</Alert>}
        <div className="flex flex-wrap items-center gap-3">
          {data.supported && data.available && !BUSY.has(phase ?? '') && (
            <Button disabled={install.isPending} onClick={() => install.mutate()}>
              Scarica e installa{data.asset_size ? ` (${formatBytes(data.asset_size)})` : ''}
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

function UpdateStatus({ data }: { data: AppUpdate }) {
  if (data.error) return <p className="text-muted-foreground">{data.error}</p>
  if (data.available) {
    return <p>È disponibile RT <span className="font-semibold tabular-nums">{data.latest}</span>
      {data.notes_url && <> · <a className="underline" href={data.notes_url} target="_blank" rel="noreferrer">novità</a></>}.</p>
  }
  if (!data.supported && data.latest && data.latest !== data.current) {
    return <p>Ultima versione stabile: <span className="tabular-nums">{data.latest}</span>.</p>
  }
  return <p className="text-muted-foreground">RT è aggiornato.</p>
}

/** Durante l'installazione RT si spegne e riparte: quando l'API risponde con la versione nuova
 * la pagina si ricarica. */
function useReloadWhenUpdated(target: string | null) {
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!target) return
    const tick = async () => {
      try {
        const res = await fetch('/api/v1/health', { cache: 'no-store' })
        const body = res.ok ? await res.json() as { version?: string } : null
        if (body?.version === target) { window.location.reload(); return }
      } catch { /* RT è spento durante l'installazione: si riprova */ }
      timer.current = window.setTimeout(tick, 2000)
    }
    timer.current = window.setTimeout(tick, 2000)
    return () => window.clearTimeout(timer.current)
  }, [target])
}
