import type { ReactNode } from 'react'

import { errorMessage } from '@/api/client'
import { useSystemInfo } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Section } from './common'

/** Scheda Info: versione e canale di aggiornamento (come 'rt -v'; il canale si cambia con
 * 'rt -u --beta' / '--stable'), cartelle e runtime. Utile da copiare in una segnalazione. */
export function InfoSection() {
  const info = useSystemInfo()
  return (
    <Section id="info" title="Info" description="Versione di RT, canale di aggiornamento e cartelle in uso: utili da allegare a una segnalazione.">
      {info.isPending && <p className="text-body text-muted-foreground">Carico le informazioni…</p>}
      {info.isError && <Alert tone="danger">{errorMessage(info.error)}</Alert>}
      {info.data && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-body sm:grid-cols-[10rem_1fr]" data-testid="system-info">
          <Row label="Versione">
            <span className="inline-flex items-center gap-2">
              <span className="font-semibold tabular-nums">{info.data.version}</span>
              {info.data.prerelease && <Badge tone="warning">Beta</Badge>}
            </span>
          </Row>
          <Row label="Canale di aggiornamento">
            {info.data.update_channel === 'beta' ? 'Beta (anche le versioni di prova)' : 'Stabile'}
          </Row>
          <Row label="Cartella dati"><Path value={info.data.data_dir} /></Row>
          <Row label="Configurazione"><Path value={info.data.config_dir} /></Row>
          <Row label="Installazione"><Path value={info.data.install_dir} /></Row>
          <Row label="Python">{info.data.python_version}</Row>
          <Row label="Sistema">{info.data.platform}</Row>
        </dl>
      )}
    </Section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-meta font-semibold text-muted-foreground sm:pt-0.5">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

function Path({ value }: { value: string }) {
  return <code className="break-all text-meta">{value}</code>
}
