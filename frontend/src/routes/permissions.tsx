import { useCallback, useEffect, useState } from 'react'

import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useReturnAddress } from '@/lib/returnAddress'
import { isAppWindow } from '@/lib/zoom'

export interface PermissionsStatus {
  platform: string
  microfono: string
  file_e_cartelle?: { rilevante: boolean; stato: string; percorso?: string | null }
  automazione_keynote?: { rilevante: boolean }
  elementi_background?: { stato: string }
  rete_locale?: { attivo: boolean }
}

interface DesktopPermissionsApi {
  stato_permessi?: () => Promise<PermissionsStatus>
  stato_microfono?: () => Promise<string>
  richiedi_microfono?: () => Promise<{ status: string }>
  apri_impostazioni_sistema?: (chiave: string) => Promise<{ ok?: boolean; errore?: string }>
}

function desktopApi(): DesktopPermissionsApi | undefined {
  return (window as unknown as { pywebview?: { api?: DesktopPermissionsApi } }).pywebview?.api
}

function StatusBadge({ stato }: { stato: string | undefined }) {
  if (!stato || stato === 'unknown' || stato === 'not_needed') return null
  if (stato === 'authorized') return <Badge tone="success">Consentito</Badge>
  if (stato === 'denied') return <Badge tone="danger">Negato</Badge>
  if (stato === 'undetermined') return <Badge tone="warning">Non ancora chiesto</Badge>
  return <Badge tone="neutral">{stato}</Badge>
}

interface PermissionRowProps {
  name: string
  purpose: string
  whenAsked: string
  status?: string
  action?: React.ReactNode
}

function PermissionRow({ name, purpose, whenAsked, status, action }: PermissionRowProps) {
  return (
    <div className="flex flex-col gap-3 border-b py-4 last:border-b-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-body font-semibold">{name}</h2>
          <StatusBadge stato={status} />
        </div>
        <p className="text-body text-foreground/90">{purpose}</p>
        <p className="text-meta text-muted-foreground">Quando viene chiesto: {whenAsked}</p>
      </div>
      {action && <div className="flex shrink-0 flex-wrap gap-2">{action}</div>}
    </div>
  )
}

export function PermissionsPage() {
  const returnAddress = useReturnAddress()
  const backTarget = !returnAddress || returnAddress === '/permessi' ? '/' : returnAddress
  const isApp = isAppWindow()

  const [status, setStatus] = useState<PermissionsStatus | null>(null)
  const [micStatus, setMicStatus] = useState<string | undefined>(undefined)
  const [busyMic, setBusyMic] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const api = desktopApi()
    if (!api) return
    try {
      if (api.stato_permessi) {
        const res = await api.stato_permessi()
        setStatus(res)
        setMicStatus(res.microfono)
      }
      if (api.stato_microfono) {
        const mic = await api.stato_microfono()
        setMicStatus(mic)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Impossibile leggere i permessi.')
    }
  }, [])

  useEffect(() => {
    if (!isApp) return
    void Promise.resolve().then(refresh)
    const onReady = () => {
      void refresh()
    }
    window.addEventListener('pywebviewready', onReady)
    return () => window.removeEventListener('pywebviewready', onReady)
  }, [isApp, refresh])

  async function openSettings(chiave: string) {
    setError(null)
    const api = desktopApi()
    if (!api?.apri_impostazioni_sistema) return
    const res = await api.apri_impostazioni_sistema(chiave)
    if (res && res.ok === false && res.errore) {
      setError(res.errore)
    }
  }

  async function askMicAgain() {
    const api = desktopApi()
    if (!api) return
    setBusyMic(true)
    setError(null)
    try {
      const current = api.stato_microfono ? await api.stato_microfono() : micStatus
      if (current === 'undetermined' && api.richiedi_microfono) {
        const res = await api.richiedi_microfono()
        setMicStatus(res.status)
        if (res.status === 'authorized') {
          await refresh()
        }
      } else if (current !== 'authorized') {
        await openSettings('microfono')
      }
      await refresh()
    } finally {
      setBusyMic(false)
    }
  }

  const platform = status?.platform
  const isMac = platform === 'darwin'
  const isWindows = platform === 'win32'

  return (
    <>
      <PageHeader title="Permessi di RT" back={{ to: backTarget, label: 'Indietro' }} />
      <PageBody>
        {!isApp ? (
          <p className="text-body text-muted-foreground">Disponibile nell&apos;app RT.</p>
        ) : !status ? (
          <p className="text-body text-muted-foreground">Controllo permessi…</p>
        ) : (
          <div className="max-w-3xl divide-y rounded-xl border bg-card px-5 py-2">
            {error && <p role="alert" className="py-3 text-sm text-danger">{error}</p>}

            {isMac && (
              <>
                <PermissionRow
                  name="Microfono"
                  purpose="Registra le note vocali e le risposte a voce durante il ripasso."
                  whenAsked="al primo avvio di una registrazione vocale."
                  status={micStatus ?? status.microfono}
                  action={
                    <>
                      <Button variant="outline" size="sm" disabled={busyMic} onClick={() => void askMicAgain()}>
                        Chiedi di nuovo
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => void openSettings('microfono')}>
                        Apri impostazioni di sistema
                      </Button>
                    </>
                  }
                />

                {status.file_e_cartelle?.rilevante && (
                  <PermissionRow
                    name="File e cartelle"
                    purpose={`Consente a RT di aprire la cartella delle lezioni${status.file_e_cartelle.percorso ? ` (${status.file_e_cartelle.percorso})` : ''}.`}
                    whenAsked="all'avvio di RT o dopo un aggiornamento dell'app se la cartella è in Scrivania, Documenti o Download."
                    status={status.file_e_cartelle.stato}
                    action={
                      <Button variant="outline" size="sm" onClick={() => void openSettings('file_e_cartelle')}>
                        Apri impostazioni di sistema
                      </Button>
                    }
                  />
                )}

                {status.automazione_keynote?.rilevante !== false && (
                  <PermissionRow
                    name="Automazione → Keynote"
                    purpose="Converte le presentazioni .pptx in PDF quando LibreOffice non è installato."
                    whenAsked="alla prima importazione di un file .pptx senza LibreOffice."
                    action={
                      <Button variant="outline" size="sm" onClick={() => void openSettings('automazione')}>
                        Apri impostazioni di sistema
                      </Button>
                    }
                  />
                )}

                <PermissionRow
                  name="Elementi in background"
                  purpose="Mantiene attivi i servizi locali di RT per completare i job anche quando chiudi la finestra."
                  whenAsked="all'avvio dei servizi dell'app in macOS (Impostazioni di Sistema → Generali → Elementi login ed estensioni)."
                  status={status.elementi_background?.stato}
                  action={
                    <Button variant="outline" size="sm" onClick={() => void openSettings('elementi_background')}>
                      Apri impostazioni di sistema
                    </Button>
                  }
                />

                {status.rete_locale?.attivo && (
                  <PermissionRow
                    name="Rete locale"
                    purpose="Permette di aprire le lezioni da telefono, tablet o altri dispositivi sulla stessa rete Wi‑Fi."
                    whenAsked="quando attivi l'accesso dalla stessa rete Wi‑Fi."
                    action={
                      <Button variant="outline" size="sm" onClick={() => void openSettings('rete_locale')}>
                        Apri impostazioni di sistema
                      </Button>
                    }
                  />
                )}
              </>
            )}

            {isWindows && (
              <>
                <PermissionRow
                  name="Microfono"
                  purpose="Registra le note vocali e le risposte a voce durante il ripasso."
                  whenAsked="dalle impostazioni sulla privacy di Windows per le app desktop."
                  action={
                    <Button variant="outline" size="sm" onClick={() => void openSettings('microfono')}>
                      Apri impostazioni di sistema
                    </Button>
                  }
                />

                <PermissionRow
                  name="Firewall di Windows"
                  purpose="Consente ai dispositivi sulla stessa rete Wi‑Fi di collegarsi a RT. Se compare l'avviso di Windows Defender, consenti l'accesso sulle «Reti private»."
                  whenAsked="quando attivi l'accesso dalla stessa rete Wi‑Fi."
                  action={
                    <Button variant="outline" size="sm" onClick={() => void openSettings('firewall')}>
                      Apri impostazioni di sistema
                    </Button>
                  }
                />

                <PermissionRow
                  name="Avvio e lavoro in background"
                  purpose="Su Windows l'avvio e il lavoro in background non richiedono permessi speciali."
                  whenAsked="mai richiesto dal sistema operativo."
                />
              </>
            )}
          </div>
        )}
      </PageBody>
    </>
  )
}
