import { Navigate } from 'react-router'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, unwrap } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { ConfirmDialog } from '@/components/ui/dialog'
import { useTelegramNotifications } from '@/api/telegram'
import { TopicArchiveExport } from '@/components/TopicArchiveExport'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Section } from '@/components/settings/common'
import { formatDateTime } from '@/lib/format'

export function TelegramPage() { return <Navigate to="/impostazioni/telegram" replace /> }

export function TelegramUserPanel() {
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const status = useQuery({ queryKey: ['telegram-user-status'], queryFn: () => unwrap(api.GET('/api/v1/settings/telegram/user/status')) })
  const topics = useQuery({ queryKey: ['telegram-user-topics'], queryFn: () => unwrap(api.GET('/api/v1/settings/telegram/user/topics')),
    enabled: status.data?.authorized === true, retry: false })
  const client = useQueryClient()
  const start = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/user/start', {
    body: { api_id: Number(apiId), api_hash: apiHash, phone },
  })) })
  const finish = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/user/complete', {
    body: { code, password: password || undefined },
  })), onSuccess: () => { setApiHash(''); setPassword(''); void client.invalidateQueries({ queryKey: ['telegram-user-status'] }) } })
  const revoke = useMutation({ mutationFn: () => unwrap(api.DELETE('/api/v1/settings/telegram/user/session')),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['telegram-user-status'] }) } })
  return <Section id="archivio-telegram" title="Archivio dei topic">
    {status.data?.authorized ? <>
      <Badge tone="success">Account collegato</Badge>
      <Button variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate()}>Scollega account e revoca sessione</Button>
      {revoke.isError && <Alert tone="danger">{errorMessage(revoke.error)}</Alert>}
      {topics.isPending && <p className="text-meta">Carico i topic…</p>}
      {topics.isError && <Alert tone="danger">{errorMessage(topics.error)}</Alert>}
      {topics.data?.topics.map((topic) => <TopicArchiveExport key={topic.id} topic={topic} />)}
    </> : <>
      <label className="text-meta">API ID <Input type="number" className="mt-1 block w-full rounded border p-2" value={apiId} onChange={(e) => setApiId(e.target.value)} /></label>
      <label className="text-meta">API hash <SecretInput className="mt-1 block w-full" value={apiHash} onChange={(e) => setApiHash(e.target.value)} /></label>
      <label className="text-meta">Numero Telegram (+ prefisso) <Input type="tel" className="mt-1 block w-full rounded border p-2" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
      <Button disabled={!apiId || !apiHash || !phone || start.isPending} onClick={() => start.mutate()}>Invia codice</Button>
      {start.isSuccess && <>
        <label className="text-meta">Codice ricevuto <Input className="mt-1 block w-full rounded border p-2" value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <label className="text-meta">Password 2FA (se richiesta) <SecretInput className="mt-1 block w-full" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <Button disabled={!code || finish.isPending} onClick={() => finish.mutate()}>Collega account</Button>
      </>}
      {start.isError && <Alert tone="danger">{errorMessage(start.error)}</Alert>}
      {finish.isError && <Alert tone="danger">{errorMessage(finish.error)}</Alert>}
    </>}
  </Section>
}

export function TopicResetButton({ id, name }: { id: number; name: string }) {
  const [open, setOpen] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const client = useQueryClient()
  const recreate = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/recreate-topic', {
    body: { topic_id: id, name: name ?? '', confirmation },
  })), onSuccess: () => { setOpen(false); void client.invalidateQueries({ queryKey: ['settings'] }) } })
  return (
    <div>
      {id > 1 && name && <Button variant="outline" size="sm" onClick={() => { setConfirmation(''); setOpen(true) }}>Svuota topic</Button>}
      <ConfirmDialog open={open} title={`Svuota «${name}»`} confirmLabel="Elimina e ricrea"
        confirmDisabled={confirmation !== 'confermo' || recreate.isPending} onCancel={() => setOpen(false)} onConfirm={() => recreate.mutate()}>
        <p>Telegram eliminerà definitivamente il topic {id} e tutti i messaggi. RT ne creerà uno nuovo con lo stesso nome e aggiornerà l'ID. I vecchi link non funzioneranno più.</p>
        <label className="mt-3 block" htmlFor={`confirm-topic-${id}`}>Scrivi confermo</label>
        <Input id={`confirm-topic-${id}`} className="mt-1 w-full rounded border p-2" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
        {recreate.isError && <Alert tone="danger">{errorMessage(recreate.error)}</Alert>}
      </ConfirmDialog>
    </div>
  )
}

const KIND_LABEL: Record<string, string> = { lezione_pronta: 'Lezione pronta', issue: 'Issue', prova: 'Prova' }

export function NotificationsCard() {
  const notifications = useTelegramNotifications()
  return (
    <Section id="notifiche-telegram" title="Ultime notifiche inviate">
      {notifications.isError && <Alert tone="danger">{errorMessage(notifications.error)}</Alert>}
      {notifications.data?.length === 0 && <p className="text-body text-muted-foreground">Ancora nessuna notifica inviata.</p>}
      {!!notifications.data?.length && (
        <ul className="flex flex-col divide-y text-body" aria-label="Notifiche">
          {notifications.data.map((n, i) => (
            <li key={`${n.sent_at}-${i}`} className="flex flex-col gap-0.5 py-2" data-testid="bot-notification">
              <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground">
                <Badge tone={n.ok ? 'neutral' : 'danger'}>{KIND_LABEL[n.kind] ?? n.kind}</Badge>
                <time dateTime={n.sent_at}>{formatDateTime(n.sent_at)}</time>
                {n.topic_id != null && <span>topic {n.topic_id}</span>}
                {!n.ok && <span className="text-danger">non inviata</span>}
              </div>
              <p className="whitespace-pre-line">{n.text}</p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
