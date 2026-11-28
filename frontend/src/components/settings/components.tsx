import { useState } from 'react'

import { errorMessage } from '@/api/client'
import {
  useCancelComponent,
  useComponents,
  useDeleteComponent,
  useDownloadComponent,
  type ComponentStatus,
} from '@/api/components'
import { useConverters } from '@/api/converters'
import { useSettings } from '@/api/settings'
import { ProgressBar } from '@/components/jobs/JobParts'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { formatBytes } from '@/lib/jobs'
import { SettingsGroup, SettingsRow } from './ui'
import { isComponentMissing } from './useComponentNotice'

const STATE_BADGE: Record<ComponentStatus['state'], { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' }> = {
  not_downloaded: { label: 'Non scaricato', tone: 'neutral' },
  downloading: { label: 'In download', tone: 'neutral' },
  paused: { label: 'In pausa', tone: 'warning' },
  ready: { label: 'Pronto', tone: 'success' },
  error: { label: 'Errore', tone: 'danger' },
}

function badgeForComponent(c: ComponentStatus): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
  if (c.id === 'browser' && c.state === 'not_downloaded' && c.system_browser) {
    return { label: 'Non necessario', tone: 'neutral' }
  }
  return STATE_BADGE[c.state]
}

const LIBREOFFICE_URL = 'https://www.libreoffice.org/download/'

function sizeSummary(c: ComponentStatus): string {
  if (c.state === 'ready') {
    return formatBytes(c.downloaded_bytes || c.approx_bytes)
  }
  if ((c.state === 'downloading' || c.state === 'paused') && c.downloaded_bytes > 0) {
    const total = c.total_bytes || c.approx_bytes
    return `${formatBytes(c.downloaded_bytes)} di ${formatBytes(total)}`
  }
  return `~${formatBytes(c.approx_bytes)}`
}

export function ComponentProgressDetails({ component }: { component: ComponentStatus }) {
  const showBar = component.state === 'downloading' || component.state === 'paused'
  return (
    <div className="flex flex-col gap-1.5" data-testid={`component-progress-${component.id}`}>
      <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground">
        <span>{component.detail}</span>
        <span>·</span>
        <span className="tabular-nums">{sizeSummary(component)}</span>
        {showBar && component.percent != null && (
          <>
            <span>·</span>
            <span className="font-medium text-foreground tabular-nums">{component.percent}%</span>
          </>
        )}
        {component.state === 'downloading' && component.eta_label && (
          <>
            <span>·</span>
            <span>{component.eta_label}</span>
          </>
        )}
      </div>
      {showBar && (
        <ProgressBar
          value={component.percent ?? null}
          label={component.name}
          className="h-1.5"
        />
      )}
      {component.state === 'error' && component.error && (
        <p className="text-meta text-danger" role="alert">
          {component.error}
        </p>
      )}
      {!component.available && component.unavailable_reason && (
        <p className="text-meta text-muted-foreground">{component.unavailable_reason}</p>
      )}
    </div>
  )
}

export function ComponentActions({
  component,
  allowDelete = true,
  onConfirmDelete,
}: {
  component: ComponentStatus
  allowDelete?: boolean
  onConfirmDelete?: (component: ComponentStatus) => void
}) {
  const download = useDownloadComponent()
  const cancel = useCancelComponent()
  const busy = download.isPending || cancel.isPending

  if (!component.available) {
    return null
  }

  const failure = download.error ?? cancel.error
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {failure && (
        <span className="text-meta text-danger" role="alert">
          {errorMessage(failure)}
        </span>
      )}
      {component.state === 'not_downloaded' && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => download.mutate(component.id)}
        >
          Scarica
        </Button>
      )}
      {component.state === 'downloading' && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => cancel.mutate(component.id)}
        >
          Pausa
        </Button>
      )}
      {component.state === 'paused' && (
        <>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => download.mutate(component.id)}
          >
            Riprendi
          </Button>
          {allowDelete && onConfirmDelete && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onConfirmDelete(component)}
            >
              Elimina
            </Button>
          )}
        </>
      )}
      {component.state === 'error' && (
        <>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => download.mutate(component.id)}
          >
            Riprova
          </Button>
          {allowDelete && component.downloaded_bytes > 0 && onConfirmDelete && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onConfirmDelete(component)}
            >
              Elimina
            </Button>
          )}
        </>
      )}
      {component.state === 'ready' && allowDelete && onConfirmDelete && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onConfirmDelete(component)}
        >
          Elimina
        </Button>
      )}
    </div>
  )
}

export function PresentationsRow() {
  const converters = useConverters()
  const pptx = converters.data?.pptx

  let statusText = 'Controllo dei convertitori…'
  let hint: string | null = null
  let showLink = false

  if (pptx) {
    if (pptx.methods.length > 0) {
      statusText = `Presentazioni .pptx convertite con: ${pptx.methods.join(', ')}`
    } else if (pptx.quicklook_available) {
      statusText = 'Presentazioni .pptx convertite con: Quick Look (qualità ridotta)'
      hint =
        pptx.platform === 'darwin'
          ? 'Per una qualità migliore puoi installare LibreOffice (gratuito) o Keynote.'
          : 'Per una qualità migliore puoi installare LibreOffice (gratuito).'
      showLink = true
    } else {
      statusText = 'Presentazioni .pptx convertite con: nessuno (solo testo)'
      hint =
        pptx.platform === 'darwin'
          ? 'Per vedere le slide come immagini puoi installare LibreOffice (gratuito) o Keynote, oppure esportare in PDF.'
          : 'Per vedere le slide come immagini puoi installare LibreOffice (gratuito) o PowerPoint, oppure esportare in PDF.'
      showLink = true
    }
  }

  return (
    <SettingsRow
      testId="presentations-row"
      label="Presentazioni"
      description={
        <span className="flex flex-col gap-1">
          <span>{statusText}</span>
          {hint && (
            <span>
              {hint}{' '}
              {showLink && (
                <a
                  href={LIBREOFFICE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:no-underline"
                >
                  Scarica LibreOffice
                </a>
              )}
            </span>
          )}
        </span>
      }
      control={
        pptx ? (
          <Badge tone={pptx.available ? 'success' : pptx.quicklook_available ? 'warning' : 'neutral'}>
            {pptx.available ? 'Pronto' : pptx.quicklook_available ? 'Qualità ridotta' : 'Solo testo'}
          </Badge>
        ) : null
      }
    />
  )
}

export function ComponentsSection() {
  const components = useComponents()
  const settings = useSettings()
  const remove = useDeleteComponent()
  const [confirmDelete, setConfirmDelete] = useState<ComponentStatus | null>(null)

  const rawItems = Array.isArray(components.data) ? components.data : []
  const stt = settings.data?.transcription
  const items = rawItems.filter((c) => {
    if (c.id === 'macparakeet') {
      return c.available || c.state !== 'not_downloaded'
    }
    if (c.id === 'transcription') {
      if (stt?.macparakeet_available) {
        return stt.engine === 'parakeet' || stt.effective_engine === 'parakeet' || c.state === 'downloading'
      }
      return true
    }
    return true
  })

  return (
    <SettingsGroup
      id="componenti"
      title="Componenti di RT"
      description="Componenti locali usati da RT per trascrivere l'audio, catturare visualizzazioni e convertire le slide."
    >
      {components.isPending && <p className="px-4 py-3 text-body text-muted-foreground">Controllo i componenti…</p>}
      {components.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(components.error)}</Alert>
        </div>
      )}
      {items.map((c) => {
        const badge = badgeForComponent(c)
        const showDot = isComponentMissing(c)
        return (
          <SettingsRow
            key={c.id}
            testId={`component-row-${c.id}`}
            infoLabel={c.name}
            label={
              <span className="inline-flex items-center gap-2">
                <span>{c.name}</span>
                {showDot && (
                  <span
                    role="img"
                    aria-label={`${c.name} da scaricare`}
                    data-testid={`component-row-dot-${c.id}`}
                    className="inline-block size-2.5 shrink-0 rounded-full bg-success"
                  />
                )}
              </span>
            }
            description={
              <span className="flex flex-col gap-1">
                <span>{c.description}</span>
                <ComponentProgressDetails component={c} />
              </span>
            }
            control={
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Badge tone={badge.tone} data-testid={`component-badge-${c.id}`}>
                  {badge.label}
                </Badge>
                <ComponentActions component={c} onConfirmDelete={setConfirmDelete} />
              </div>
            }
          />
        )
      })}
      <PresentationsRow />
      <ConfirmDialog
        open={confirmDelete !== null}
        title={`Eliminare ${confirmDelete?.name ?? 'questo componente'}?`}
        confirmLabel="Elimina"
        confirmDisabled={remove.isPending}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (!confirmDelete) return
          remove.mutate(confirmDelete.id, { onSettled: () => setConfirmDelete(null) })
        }}
      >
        <p>I file scaricati verranno rimossi dal disco. Potrai riscaricarli in qualsiasi momento da questa pagina.</p>
        {remove.isError && <Alert tone="danger" className="mt-3">{errorMessage(remove.error)}</Alert>}
      </ConfirmDialog>
    </SettingsGroup>
  )
}
