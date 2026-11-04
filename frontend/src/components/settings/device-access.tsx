import { useEffect, useMemo, useState } from 'react'
import { Copy } from 'lucide-react'
import { encode } from 'uqr'

import { errorMessage } from '@/api/client'
import { useLoginLink, useTailnet } from '@/api/hooks'
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
import { Field, Section } from './common'
import { HelpLink } from '@/components/guide/HelpLink'

/** Accesso da iPhone o da un altro computer: un QR con il link monouso (5 minuti, una volta).
 * Se il Mac ha aperto RT su 127.0.0.1 l'indirizzo per l'altro dispositivo è quello della tailnet
 * che il Mac stesso rileva (https://nome-mac.tailnet.ts.net, l'unico per cui vale il certificato
 * di Tailscale); senza Tailscale si scrive a mano (rete locale: http://nome-mac.local:8765). */
export function DeviceAccessSection() {
  const here = window.location.origin
  const tailnet = useTailnet().data
  const [saved] = useState(readDeviceOrigin)
  // null finché non si scrive nel campo: intanto vale l'indirizzo proposto (salvato, pagina o tailnet)
  const [typed, setTyped] = useState<string | null>(null)
  const [link, setLink] = useState<{ url: string; expiresAt: number } | null>(null)
  const loginLink = useLoginLink()
  const detected = tailnet?.origin ?? null
  const address = typed ?? preferredOrigin(saved, here, detected)
  const origin = normalizeOrigin(address)

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
    <Section
      id="altro-dispositivo"
      title={
        <span className="inline-flex items-center gap-1.5">
          <span>Accesso da un altro dispositivo</span>
          <HelpLink to="/guida/iphone-e-agenti#accesso-da-iphone" label="Guida sull'accesso da iPhone" />
        </span>
      }
      description="Apri RT da iPhone inquadrando un QR: il link entra una sola volta e vale 5 minuti."
    >
      <Field
        label="Indirizzo di RT per l'altro dispositivo"
        htmlFor="device-origin"
        hint={
          <>
            Con Tailscale Serve è <code>https://nome-mac.tailnet.ts.net</code>; in rete locale{' '}
            <code>http://nome-mac.local:8765</code>. 127.0.0.1 funziona solo su questo Mac.
          </>
        }
      >
        <Input
          id="device-origin"
          inputMode="url"
          autoComplete="off"
          value={address}
          placeholder="https://nome-mac.tailnet.ts.net"
          onChange={(e) => {
            setTyped(e.target.value)
            setLink(null)
          }}
        />
      </Field>
      {origin && isLoopback(origin) && (
        <Alert tone="warning">Questo indirizzo raggiunge solo il Mac stesso: da iPhone non si apre.</Alert>
      )}
      {origin && isHttpsIp(origin) && (
        <Alert tone="warning">
          Con l'indirizzo IP la connessione sicura non riesce: il certificato di Tailscale vale solo per il nome del Mac
          {detected ? (
            <>
              , cioè <code>{detected}</code>
            </>
          ) : (
            ' (https://nome-mac.tailnet.ts.net)'
          )}
          .
        </Alert>
      )}
      {tailnet && detected && origin === detected && !tailnet.serve && (
        <Alert tone="warning">
          Tailscale Serve non è attivo su questo Mac: nel Terminale esegui <code>tailscale serve --bg 8765</code>, poi
          crea il QR.
        </Alert>
      )}
      {tailnet && detected && origin === detected && tailnet.funnel && (
        <Alert tone="warning">
          Questo indirizzo è pubblico su Internet (Tailscale Funnel): per tenerlo nella sola tailnet esegui{' '}
          <code>tailscale serve --bg 8765</code>, che spegne il Funnel.
        </Alert>
      )}
      <div>
        <Button onClick={create} disabled={!origin || loginLink.isPending}>
          {link ? 'Crea un nuovo QR' : 'Crea QR di accesso'}
        </Button>
      </div>
      {loginLink.isError && <Alert tone="danger">{errorMessage(loginLink.error)}</Alert>}
      {link && <LinkQr key={link.url} url={link.url} expiresAt={link.expiresAt} />}

      <ReadonlyKeyManager />
    </Section>
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
  const baseUrl = info?.base_url || 'http://127.0.0.1:8765/api/v1/readonly'
  const promptText = activeKey ? buildAgentPrompt(baseUrl, activeKey) : ''

  return (
    <div className="mt-8 border-t border-border/60 pt-6" data-testid="readonly-api-section">
      <div className="flex flex-col gap-1">
        <h3 className="text-body font-semibold text-foreground">API di sola lettura (agenti e Open WebUI)</h3>
        <p className="text-meta text-muted-foreground">
          Chiave separata di sola lettura per consultare le lezioni su 127.0.0.1 con agenti o assistenti locali.
        </p>
      </div>

      {info?.configured && activeKey && (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-meta font-medium text-foreground">Chiave API:</span>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={activeKey}
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
              {promptText}
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
        <code className="text-foreground">{baseUrl}/openapi.json</code>
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
        <p>Inquadralo con la fotocamera dell'iPhone. Scade tra {formatSeconds(secondsLeft)}.</p>
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
