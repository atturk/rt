import { useEffect, useMemo, useState } from 'react'
import { encode } from 'uqr'

import { errorMessage } from '@/api/client'
import { useLoginLink } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { deviceLoginUrl, isLoopback, normalizeOrigin, readDeviceOrigin, saveDeviceOrigin } from '@/lib/deviceLogin'
import { Field, Section } from './common'

/** Accesso da iPhone o da un altro computer: un QR con il link monouso (5 minuti, una volta).
 * Se il Mac ha aperto RT su 127.0.0.1 l'indirizzo per l'altro dispositivo va scritto a mano
 * (Tailscale: https://nome-mac.tailnet.ts.net, rete locale: http://nome-mac.local:8765). */
export function DeviceAccessSection() {
  const here = window.location.origin
  const [address, setAddress] = useState(() => readDeviceOrigin() || (isLoopback(here) ? '' : here))
  const [link, setLink] = useState<{ url: string; expiresAt: number } | null>(null)
  const loginLink = useLoginLink()
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
      title="Accesso da un altro dispositivo"
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
            setAddress(e.target.value)
            setLink(null)
          }}
        />
      </Field>
      {origin && isLoopback(origin) && (
        <Alert tone="warning">Questo indirizzo raggiunge solo il Mac stesso: da iPhone non si apre.</Alert>
      )}
      <div>
        <Button onClick={create} disabled={!origin || loginLink.isPending}>
          {link ? 'Crea un nuovo QR' : 'Crea QR di accesso'}
        </Button>
      </div>
      {loginLink.isError && <Alert tone="danger">{errorMessage(loginLink.error)}</Alert>}
      {link && <LinkQr key={link.url} url={link.url} expiresAt={link.expiresAt} />}
    </Section>
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
  if (secondsLeft <= 0) return <p className="text-sm text-muted-foreground">Il QR è scaduto: creane uno nuovo.</p>
  return (
    <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
      <QrCode value={url} />
      <div className="flex min-w-0 flex-col gap-1 text-sm">
        <p>Inquadralo con la fotocamera dell'iPhone. Scade tra {formatSeconds(secondsLeft)}.</p>
        <code className="break-all text-xs text-muted-foreground" data-testid="device-login-url">{url}</code>
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
