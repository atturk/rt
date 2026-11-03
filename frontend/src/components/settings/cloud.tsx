import { ExternalLink, RefreshCw } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import {
  useCloudCheckout, useCloudLoginStart, useCloudLoginVerify, useCloudLogout, useCloudPortal, useCloudStatus,
  useCloudSync, type CloudStatus,
} from '@/api/cloud'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field, Section } from './common'

/** Modalità facilitata: niente chiavi né modelli da configurare. Si accede con un codice via
 * email, si paga un abbonamento mensile e RT crea da solo la connessione "RT Cloud". */

const usd = (n: number | null | undefined) => (n == null ? '—' : `${n.toFixed(2)} $`)

function LoginForm() {
  const start = useCloudLoginStart()
  const verify = useCloudLoginVerify()
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const sent = start.isSuccess

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!sent) start.mutate(email.trim())
    else verify.mutate({ email: email.trim(), code: code.trim() })
  }

  const error = start.isError ? errorMessage(start.error) : verify.isError ? errorMessage(verify.error) : null
  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label="Accesso a RT Cloud">
      <Field label="Email" htmlFor="cloud-email">
        <Input id="cloud-email" type="email" autoComplete="email" value={email} disabled={sent} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      {sent && (
        <Field label="Codice ricevuto per email" htmlFor="cloud-code" hint="Scade tra 10 minuti.">
          <Input id="cloud-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
        </Field>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={sent ? code.trim().length !== 6 || verify.isPending : !email.includes('@') || start.isPending}>
          {sent ? 'Accedi' : 'Mandami il codice'}
        </Button>
        {sent && (
          <Button type="button" variant="outline" onClick={() => { start.reset(); verify.reset(); setCode('') }}>
            Cambia email
          </Button>
        )}
      </div>
    </form>
  )
}

function Subscribe({ onSynced }: { onSynced?: () => void }) {
  const checkout = useCloudCheckout()
  const sync = useCloudSync()
  const url = checkout.data?.url
  const active = sync.data?.subscription && ['active', 'canceled'].includes(sync.data.subscription.status)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-body">
        Con l'abbonamento mensile RT usa modelli già scelti, senza chiavi da configurare. Il credito si rinnova ogni mese e
        quello non usato non si accumula.
      </p>
      <div className="flex flex-wrap gap-2">
        {url ? (
          <a href={url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-body font-medium text-primary-foreground">
            Apri la pagina di pagamento <ExternalLink className="size-4" aria-hidden />
          </a>
        ) : (
          <Button onClick={() => checkout.mutate(undefined)} disabled={checkout.isPending}>Abbonati</Button>
        )}
        {url && (
          <Button variant="outline" onClick={() => sync.mutate(true, { onSuccess: (d) => { if (d.subscription?.status === 'active') onSynced?.() } })} disabled={sync.isPending}>
            Ho pagato, attiva
          </Button>
        )}
      </div>
      {sync.isSuccess && !active && <Alert tone="warning">Il pagamento non risulta ancora: riprova tra qualche secondo.</Alert>}
      {checkout.isError && <Alert tone="danger">{errorMessage(checkout.error)}</Alert>}
      {sync.isError && <Alert tone="danger">{errorMessage(sync.error)}</Alert>}
    </div>
  )
}

function Account({ status, onSynced }: { status: CloudStatus; onSynced?: () => void }) {
  const sync = useCloudSync()
  const portal = useCloudPortal()
  const logout = useCloudLogout()
  const sub = status.subscription
  const active = !!sub && ['active', 'canceled'].includes(sub.status)
  const balance = status.balance
  const share = balance?.limit_usd ? Math.max(0, Math.min(1, (balance.remaining_usd ?? 0) / balance.limit_usd)) : 0
  return (
    <div className="flex flex-col gap-3">
      <p className="text-body">
        Account: <strong>{status.email}</strong>
      </p>
      {active ? (
        <>
          <div className="flex flex-col gap-1" data-testid="cloud-balance">
            <p className="text-body">
              Credito rimasto: <strong>{usd(balance?.remaining_usd)}</strong>
              {balance?.limit_usd != null && <span className="text-muted-foreground"> · usati {usd(balance.usage_usd)}</span>}
            </p>
            <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Credito rimasto" aria-valuenow={Math.round(share * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-primary" style={{ width: `${share * 100}%` }} />
            </div>
            {sub?.status === 'canceled' && (
              <p className="text-meta text-muted-foreground">Abbonamento disdetto: resta attivo fino alla fine del periodo pagato.</p>
            )}
          </div>
          {!status.connection && (
            <Alert tone="warning">La connessione RT Cloud non è ancora configurata: premi Aggiorna.</Alert>
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => sync.mutate(false)} disabled={sync.isPending}>
              <RefreshCw aria-hidden /> Aggiorna
            </Button>
            {portal.data?.url ? (
              <a href={portal.data.url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-md border px-4 text-body">
                Apri il portale <ExternalLink className="size-4" aria-hidden />
              </a>
            ) : (
              <Button variant="outline" onClick={() => portal.mutate()} disabled={portal.isPending}>Gestisci abbonamento</Button>
            )}
          </div>
        </>
      ) : (
        <Subscribe onSynced={onSynced} />
      )}
      {sync.isError && <Alert tone="danger">{errorMessage(sync.error)}</Alert>}
      {portal.isError && <Alert tone="danger">{errorMessage(portal.error)}</Alert>}
      <div>
        <Button variant="ghost" size="sm" onClick={() => logout.mutate(undefined)} disabled={logout.isPending}>Scollega account</Button>
      </div>
    </div>
  )
}

/** Contenuto riusato dalla configurazione guidata e dalla pagina Modelli. */
export function CloudPanel({ onSynced }: { onSynced?: () => void }) {
  const status = useCloudStatus()
  if (status.isPending) return <p className="text-body text-muted-foreground">Controllo RT Cloud…</p>
  if (status.isError) return <Alert tone="danger">{errorMessage(status.error)}</Alert>
  if (!status.data.available) return <Alert>La modalità facilitata non è ancora disponibile.</Alert>
  return status.data.logged_in ? <Account status={status.data} onSynced={onSynced} /> : <LoginForm />
}

/** Sezione nella pagina Modelli; nascosta finché RT Cloud non è pubblicato. */
export function CloudSection() {
  const status = useCloudStatus()
  if (!status.data?.available) return null
  return (
    <Section title="RT Cloud (modalità facilitata)" id="rt-cloud">
      <CloudPanel />
    </Section>
  )
}
