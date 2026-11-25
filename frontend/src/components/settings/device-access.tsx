import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Copy } from 'lucide-react'
import { encode } from 'uqr'

import { errorMessage } from '@/api/client'
import { useLan, useLoginLink, useSetLan, useTailnet } from '@/api/hooks'
import { useCreateReadonlyKey, useReadonlyKey, useRevokeReadonlyKey } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { formatDateTime } from '@/lib/format'
import {
  deviceLoginUrl,
  isHttpsIp,
  isLoopback,
  normalizeOrigin,
  preferredOrigin,
  readDeviceOrigin,
  saveDeviceOrigin,
} from '@/lib/deviceLogin'
import { SettingsGroup, SettingsPage, SettingsRow } from './ui'

/** Accesso da un altro dispositivo (telefono, tablet, computer): un QR con il link monouso (5 minuti, una volta).
 * Due strade affiancate: la stessa rete locale (http, non cifrata: casa o hotspot) e Tailscale (https, ovunque). */
export function DeviceAccessSection() {
  return (
    <SettingsPage
      title="Accesso da altri dispositivi"
      description="Apri RT da un telefono, un tablet o un altro computer inquadrando un QR: il link entra una sola volta e vale 5 minuti."
    >
      <div id="altro-dispositivo" className="grid gap-6 lg:grid-cols-2">
        <LanPanel />
        <TailscalePanel />
      </div>
      <ReadonlyKeyManager />
    </SettingsPage>
  )
}

function Panel({ title, testId, children }: { title: string; testId: string; children: ReactNode }) {
  return (
    <SettingsGroup title={title}>
      <div className="flex min-w-0 flex-col gap-3 p-4" data-testid={testId}>
        {children}
      </div>
    </SettingsGroup>
  )
}

/** Stessa rete: "Abilita e crea QR" fa ascoltare RT anche sulla rete del computer (si riavvia da solo)
 * e crea subito il QR, che porta all'indirizzo del computer in quella rete (http://nome.local:porta o
 * l'IP), mai a 127.0.0.1. Si spegne con "Spegni", uscendo da RT o cambiando rete. */
function LanPanel() {
  const here = window.location.origin
  const onThisComputer = isLoopback(here)
  // riavvio in corso dal momento della scelta finché l'API non risponde come richiesto
  const [waitSince, setWaitSince] = useState<number | null>(null)
  const [polling, setPolling] = useState(false)
  const wantQr = useRef(false)
  const lan = useLan(polling)
  const setLan = useSetLan()
  const info = lan.data
  const settled = !!info && info.enabled === info.active && lan.dataUpdatedAt > (waitSince ?? 0)
  const waiting = waitSince !== null && !settled
  if (polling && !waiting) setPolling(false)
  const ready = !!info?.enabled && !!info?.active && !waiting
  const addresses = info?.addresses ?? []
  const [chosen, setChosen] = useState<string | null>(null)
  const origin = chosen && addresses.includes(chosen) ? chosen : (addresses[0] ?? null)
  const [link, setLink] = useState<{ url: string; expiresAt: number } | null>(null)
  const loginLink = useLoginLink()

  const createFor = (target: string) => {
    loginLink.mutate(undefined, {
      onSuccess: (data) => {
        const url = deviceLoginUrl(data.url, target)
        setLink(url ? { url, expiresAt: Date.now() + data.expires_in * 1000 } : null)
      },
    })
  }

  // il QR chiesto con "Abilita e crea QR" arriva appena RT ascolta sulla rete
  const createLater = useRef(createFor)
  useEffect(() => {
    createLater.current = createFor
  })
  useEffect(() => {
    if (wantQr.current && ready && origin) {
      wantQr.current = false
      createLater.current(origin)
    }
  }, [ready, origin])

  const turn = (next: boolean) => {
    setLink(null)
    wantQr.current = next
    setLan.mutate(next, {
      onSuccess: (data) => {
        const restarting = !!data?.restarting
        setWaitSince(restarting ? Date.now() : null)
        setPolling(restarting)
      },
      onError: () => {
        wantQr.current = false
      },
    })
  }

  return (
    <Panel title="Stessa rete Wi‑Fi (senza Tailscale)" testId="device-access-lan">
      <p className="text-body text-muted-foreground">
        Collega questo computer e l'altro dispositivo alla stessa rete, poi crea il QR: ogni dispositivo di quella rete può
        entrare con il link.
      </p>
      <p className="text-body text-muted-foreground">
        È pensato per le reti private, come la Wi‑Fi di casa o l'hotspot del tuo telefono. Sulle reti pubbliche (università,
        biblioteche, bar) è meglio non usarlo, perché la connessione non è cifrata: lì, o quando non sei sulla stessa rete, usa
        Tailscale. Si spegne da solo quando esci da RT o quando il computer cambia rete.
      </p>
      {!onThisComputer && !ready && (
        <p className="text-meta text-muted-foreground">Si abilita dal computer su cui gira RT.</p>
      )}
      {setLan.isError && <Alert tone="danger">{errorMessage(setLan.error)}</Alert>}
      {waiting ? (
        <Alert>RT si prepara per la rete locale: qualche secondo…</Alert>
      ) : ready ? (
        <>
          {addresses.length > 1 && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-meta text-muted-foreground">Indirizzo per l'altro dispositivo</legend>
              {addresses.map((address) => (
                <label key={address} className="flex items-center gap-2 text-body">
                  <input
                    type="radio"
                    name="lan-address"
                    value={address}
                    checked={origin === address}
                    onChange={() => {
                      setChosen(address)
                      setLink(null)
                    }}
                  />
                  <code className="break-all">{address}</code>
                </label>
              ))}
            </fieldset>
          )}
          {addresses.length === 0 && (
            <Alert tone="warning">Non trovo l'indirizzo di questo computer nella rete: controlla di essere collegato alla Wi‑Fi.</Alert>
          )}
          <p className="text-meta text-muted-foreground">
            Il nome che finisce in .local resta valido anche se l'IP cambia; se non si apre (capita su alcuni Android) usa
            l'indirizzo con i numeri. Se macOS chiede di consentire le connessioni in entrata a RT, rispondi Consenti.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => origin && createFor(origin)} disabled={!origin || loginLink.isPending}>
              {link ? 'Crea un nuovo QR' : 'Crea QR per la rete locale'}
            </Button>
            {onThisComputer && (
              <Button variant="outline" onClick={() => turn(false)} disabled={setLan.isPending}>
                Spegni
              </Button>
            )}
          </div>
          {loginLink.isError && <Alert tone="danger">{errorMessage(loginLink.error)}</Alert>}
          {link && <LinkQr key={link.url} url={link.url} expiresAt={link.expiresAt} />}
        </>
      ) : (
        <>
          {info?.enabled && !info.active && (
            <Alert tone="warning">Esci da RT e riaprilo, poi abilita di nuovo la rete locale.</Alert>
          )}
          <div>
            <Button onClick={() => turn(true)} disabled={!onThisComputer || setLan.isPending}>
              Abilita e crea QR
            </Button>
          </div>
        </>
      )}
    </Panel>
  )
}

/** Comando Tailscale Serve consigliato: usa una porta HTTPS dedicata così la 443 resta libera per altre app. */
function tailscaleServeCommand(localPort: number): string {
  return `tailscale serve --bg --https=${localPort} http://127.0.0.1:${localPort}`
}

/** Per spegnere il Funnel bisogna agire sulla stessa porta HTTPS su cui il Funnel è attivo (443 se assente). */
function funnelFixCommand(origin: string, localPort: number): string {
  try {
    const httpsPort = new URL(origin).port
    if (httpsPort && httpsPort !== '443') {
      return `tailscale serve --bg --https=${httpsPort} http://127.0.0.1:${localPort}`
    }
  } catch {
    /* fallback alla porta 443 */
  }
  return `tailscale serve --bg ${localPort}`
}

/** Tailscale: se il Mac ha aperto RT su 127.0.0.1 l'indirizzo per l'altro dispositivo è quello della
 * tailnet che il Mac stesso rileva (https://nome-computer.tailnet.ts.net[:porta], l'unico per cui vale il
 * certificato di Tailscale). */
function TailscalePanel() {
  const here = window.location.origin
  const tailnet = useTailnet().data
  const localPort = tailnet?.local_port ?? 8765
  const serveCommand = tailscaleServeCommand(localPort)
  const [saved] = useState(readDeviceOrigin)
  // null finché non si scrive nel campo: intanto vale l'indirizzo proposto (salvato, pagina o tailnet)
  const [typed, setTyped] = useState<string | null>(null)
  const [link, setLink] = useState<{ url: string; expiresAt: number } | null>(null)
  const [copiedServe, setCopiedServe] = useState(false)
  const loginLink = useLoginLink()
  const detected = tailnet?.origin ?? null
  const address = typed ?? preferredOrigin(saved, here, detected, tailnet?.serve)
  const origin = normalizeOrigin(address)

  const copyServeCommand = () => {
    void navigator.clipboard?.writeText(serveCommand)
    setCopiedServe(true)
    setTimeout(() => setCopiedServe(false), 2000)
  }

  const create = () => {
    if (!origin) return
    saveDeviceOrigin(origin)
    loginLink.mutate(undefined, {
      onSuccess: (data) => {
        const url = deviceLoginUrl(data.url, origin)
        setLink(url ? { url, expiresAt: Date.now() + data.expires_in * 1000 } : null)
      },
    })
  }

  return (
    <Panel title="Tailscale (o un'altra VPN)" testId="device-access-tailscale">
      <p className="text-body text-muted-foreground">
        Funziona ovunque, anche fuori casa e sulle reti pubbliche: la connessione è cifrata e la vedono solo i tuoi dispositivi.
      </p>
      <div className="-mx-4 border-y border-border/60">
        <SettingsRow
          label="Indirizzo di RT per l'altro dispositivo"
          htmlFor="device-origin"
          stacked
          info={
            <>
              Con Tailscale Serve è <code>{`https://nome-computer.tailnet.ts.net:${localPort}`}</code> (o senza porta se RT usa la
              443). 127.0.0.1 funziona solo su questo computer.
            </>
          }
          control={
            <Input
              id="device-origin"
              inputMode="url"
              autoComplete="off"
              value={address}
              placeholder={`https://nome-computer.tailnet.ts.net:${localPort}`}
              onChange={(e) => {
                setTyped(e.target.value)
                setLink(null)
              }}
            />
          }
        />
      </div>
      {origin && isLoopback(origin) && (
        <Alert tone="warning">Questo indirizzo raggiunge solo questo computer: dagli altri dispositivi non si apre.</Alert>
      )}
      {origin && isHttpsIp(origin) && (
        <Alert tone="warning">
          Con l'indirizzo IP la connessione sicura non riesce: il certificato di Tailscale vale solo per il nome del computer
          {detected ? (
            <>
              , cioè <code className="break-all">{detected}</code>
            </>
          ) : (
            ' (https://nome-computer.tailnet.ts.net)'
          )}
          .
        </Alert>
      )}
      {tailnet && detected && origin === detected && !tailnet.serve && (
        <Alert tone="warning">
          <p>
            Tailscale Serve non è attivo su questo computer: nel Terminale (su Windows nel Prompt dei comandi) esegui{' '}
            <code className="break-all">{tailscaleServeCommand(localPort)}</code>, poi crea il QR.
          </p>
          <p className="mt-1">
            Con <code className="break-all">{`tailscale serve --bg ${localPort}`}</code> RT prende invece l'indirizzo senza porta (443).
          </p>
        </Alert>
      )}
      {tailnet && detected && origin === detected && tailnet.funnel && (
        <Alert tone="warning">
          Questo indirizzo è pubblico su Internet (Tailscale Funnel): per tenerlo nella sola tailnet esegui{' '}
          <code className="break-all">{funnelFixCommand(detected, localPort)}</code>, che spegne il Funnel.
        </Alert>
      )}
      <div>
        <Button onClick={create} disabled={!origin || loginLink.isPending}>
          {link ? 'Crea un nuovo QR' : 'Crea QR di accesso'}
        </Button>
      </div>
      {loginLink.isError && <Alert tone="danger">{errorMessage(loginLink.error)}</Alert>}
      {link && <LinkQr key={link.url} url={link.url} expiresAt={link.expiresAt} />}
      <div
        className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3 text-meta text-muted-foreground"
        data-testid="tailscale-local-port"
      >
        <span className="min-w-0">
          RT ascolta su questo computer sulla porta <code className="text-foreground">{localPort}</code>.{' '}
          <code className="break-all text-foreground">{serveCommand}</code>
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={copyServeCommand}
          className="gap-1 shrink-0"
          data-testid="copy-tailscale-command"
        >
          <Copy className="size-3.5" aria-hidden /> {copiedServe ? 'Copiato!' : 'Copia'}
        </Button>
      </div>
    </Panel>
  )
}

function buildAgentPrompt(base: string, key: string): string {
  return `Puoi leggere le mie lezioni universitarie da RT, un'app che gira su questo computer.
- API (solo lettura): ${base}
- Specifica OpenAPI: ${base}/openapi.json
- Ogni richiesta deve avere l'header: Authorization: Bearer ${key}
Prima scarica la specifica OpenAPI per sapere quali endpoint ci sono, poi usali per rispondere alle mie domande sulle lezioni.
Esempio: curl -H "Authorization: Bearer ${key}" ${base}/openapi.json
Regole: l'accesso è di sola lettura, non provare a modificare niente. Le lezioni sono mie e private: non mandarne il contenuto ad altri servizi se non te lo chiedo. L'API risponde solo da questo computer, quindi funziona con agenti che girano qui (per esempio Antigravity, Claude Code, Codex, pi), non con quelli nel cloud.`
}

function ReadonlyKeyManager() {
  const query = useReadonlyKey()
  const tailnet = useTailnet().data
  const createKey = useCreateReadonlyKey()
  const revokeKey = useRevokeReadonlyKey()
  const [copiedKey, setCopiedKey] = useState(false)
  const [copiedPrompt, setCopiedPrompt] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState(false)

  const handleCreate = () => {
    createKey.mutate(undefined)
  }

  const handleRevoke = () => {
    revokeKey.mutate(undefined, {
      onSuccess: () => {
        setConfirmRevoke(false)
      },
    })
  }

  const copyToClipboard = (text: string, isPrompt: boolean) => {
    void navigator.clipboard?.writeText(text)
    if (isPrompt) {
      setCopiedPrompt(true)
      setTimeout(() => setCopiedPrompt(false), 2000)
    } else {
      setCopiedKey(true)
      setTimeout(() => setCopiedKey(false), 2000)
    }
  }

  const info = query.data
  const activeKey = info?.key ?? null
  const fallbackPort = tailnet?.local_port ?? (Number(window.location.port) || 8765)
  const baseUrl = info?.base_url || `http://127.0.0.1:${fallbackPort}/api/v1/readonly`
  const promptText = activeKey ? buildAgentPrompt(baseUrl, activeKey) : ''
  // a schermo la chiave resta nascosta: si copia intera con Copia / Copia prompt
  const maskedKey = activeKey ? `${activeKey.slice(0, 4)}${'•'.repeat(12)}` : ''
  const promptShown = activeKey ? buildAgentPrompt(baseUrl, maskedKey) : ''

  return (
    <SettingsGroup
      id="readonly-api"
      title="API di sola lettura (agenti e Open WebUI)"
      description="Chiave separata di sola lettura per consultare le lezioni su 127.0.0.1 con agenti o assistenti locali."
    >
      <div className="p-4" data-testid="readonly-api-section">

      {info?.configured && activeKey && (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-meta font-medium text-foreground">Chiave API:</span>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={maskedKey}
                aria-label="Chiave API (nascosta, usa Copia)"
                className="w-full rounded border bg-muted/40 px-3 py-1.5 font-mono text-body text-foreground"
                data-testid="readonly-key-value"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => copyToClipboard(activeKey, false)}
                className="gap-1 shrink-0"
                data-testid="copy-readonly-key"
              >
                <Copy className="size-3.5" aria-hidden /> {copiedKey ? 'Copiata!' : 'Copia'}
              </Button>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-4" data-testid="readonly-agent-prompt-box">
            <div className="flex items-center justify-between gap-2 pb-2 border-b border-border/60">
              <span className="text-body font-semibold text-foreground">Prompt per un agente</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => copyToClipboard(promptText, true)}
                className="gap-1 shrink-0"
                data-testid="copy-agent-prompt"
              >
                <Copy className="size-3.5" aria-hidden /> {copiedPrompt ? 'Prompt copiato!' : 'Copia prompt'}
              </Button>
            </div>
            <pre className="mt-3 whitespace-pre-wrap font-mono text-meta text-muted-foreground break-all" data-testid="agent-prompt-text">
              {promptShown}
            </pre>
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-body">
          <span className="font-medium text-foreground">Stato chiave:</span>
          {info?.configured ? (
            <span className="inline-flex items-center gap-1.5 text-ok font-medium" data-testid="readonly-key-status">
              <span className="size-2 rounded-full bg-ok" />
              Attiva {info.key_preview ? `(${info.key_preview})` : ''}
              {info.created_at && (
                <span className="text-meta text-muted-foreground font-normal">
                  · creata {formatDateTime(info.created_at)}
                </span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground" data-testid="readonly-key-status">Non configurata</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={info?.configured ? 'outline' : 'default'}
            size="sm"
            onClick={handleCreate}
            disabled={createKey.isPending}
            data-testid="btn-create-readonly-key"
          >
            {info?.configured ? 'Rigenera chiave' : 'Crea chiave'}
          </Button>

          {info?.configured && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setConfirmRevoke(true)}
              disabled={revokeKey.isPending}
              data-testid="btn-revoke-readonly-key"
            >
              Revoca
            </Button>
          )}
        </div>
      </div>

      <div className="mt-3 text-meta text-muted-foreground">
        URL specifica OpenAPI:{' '}
        <code className="break-all text-foreground">{baseUrl}/openapi.json</code>
      </div>

      <ConfirmDialog
        open={confirmRevoke}
        title="Revoca chiave di sola lettura"
        confirmLabel="Revoca"
        confirmDisabled={revokeKey.isPending}
        onCancel={() => setConfirmRevoke(false)}
        onConfirm={handleRevoke}
      >
        <p>Revocare la chiave di sola lettura?</p>
        <p className="mt-2 text-meta text-muted-foreground">
          Agenti, Open WebUI e gli altri client locali non potranno più accedere alle lezioni finché non generi una nuova chiave.
        </p>
      </ConfirmDialog>
      </div>
    </SettingsGroup>
  )
}

/** QR e conto alla rovescia; montato di nuovo (key) per ogni link. */
function LinkQr({ url, expiresAt }: { url: string; expiresAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  const secondsLeft = Math.max(0, Math.ceil((expiresAt - now) / 1000))
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  if (secondsLeft <= 0) return <p className="text-body text-muted-foreground">Il QR è scaduto: creane uno nuovo.</p>
  return (
    <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
      <QrCode value={url} />
      <div className="flex min-w-0 flex-col gap-1 text-body">
        <p>Inquadralo con la fotocamera del telefono o del tablet. Scade tra {formatSeconds(secondsLeft)}.</p>
        <code className="break-all text-meta text-muted-foreground" data-testid="device-login-url">{url}</code>
      </div>
    </div>
  )
}

function formatSeconds(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** QR in SVG, sempre nero su bianco (anche col tema scuro) perché le fotocamere lo leggano. */
function QrCode({ value }: { value: string }) {
  const { path, size } = useMemo(() => {
    const qr = encode(value, { ecc: 'M', border: 0 })
    const d = qr.data.flatMap((row, y) => row.flatMap((dark, x) => (dark ? [`M${x} ${y}h1v1h-1z`] : []))).join('')
    return { path: d, size: qr.size }
  }, [value])
  return (
    <svg
      role="img"
      aria-label="QR del link di accesso"
      viewBox={`-4 -4 ${size + 8} ${size + 8}`}
      className="size-48 shrink-0 rounded-md bg-white"
      shapeRendering="crispEdges"
    >
      <path d={path} fill="#000" />
    </svg>
  )
}
