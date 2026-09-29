import { Bot } from 'lucide-react'
import { Link } from 'react-router'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage, unwrap } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { useSettings, useTopicTest, type Settings } from '@/api/settings'
import { useTelegramNotifications } from '@/api/telegram'
import { RevealableValue, TopicTestButton, TopicTestResult } from '@/components/settings/telegram'
import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import { TopicArchiveExport } from '@/components/TopicArchiveExport'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { formatDateTime } from '@/lib/format'
import type { Area } from './types'

const SETTINGS_LINK = '/impostazioni#telegram'

function TelegramPage() {
  const settings = useSettings()
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-bold tracking-tight">Bot Telegram</h1>
        <Link to={SETTINGS_LINK} className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground">
          Impostazioni Telegram
        </Link>
      </div>
      <TelegramBotPanel />
      {settings.isPending && <p className="text-sm text-muted-foreground">Carico gruppo e topic…</p>}
      {settings.isError && <Alert tone="danger">{errorMessage(settings.error)}</Alert>}
      {settings.data && <GroupCard settings={settings.data} />}
      <TelegramUserPanel />
      {settings.data && <TopicsCard settings={settings.data} />}
      <NotificationsCard />
    </section>
  )
}

function TelegramUserPanel() {
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
  return <Card className="flex flex-col gap-3 p-5" role="region" aria-label="Archivio Telegram">
    <h2 className="text-base font-bold">Archivio dei topic</h2>
    <p className="text-xs text-muted-foreground">Per leggere la cronologia completa e scaricare i media collega un account Telegram utente autorizzato nel gruppo. Il bot da solo non può recuperare i vecchi messaggi.</p>
    {status.data?.authorized ? <>
      <Badge tone="success">Account collegato</Badge>
      <Button variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate()}>Scollega account e revoca sessione</Button>
      {revoke.isError && <Alert tone="danger">{errorMessage(revoke.error)}</Alert>}
      {topics.isPending && <p className="text-xs">Carico i topic…</p>}
      {topics.isError && <Alert tone="danger">{errorMessage(topics.error)}</Alert>}
      {topics.data?.topics.map((topic) => <TopicArchiveExport key={topic.id} topic={topic} />)}
    </> : <>
      <label className="text-xs">API ID <input type="number" className="mt-1 block w-full rounded border p-2" value={apiId} onChange={(e) => setApiId(e.target.value)} /></label>
      <label className="text-xs">API hash <input type="password" className="mt-1 block w-full rounded border p-2" value={apiHash} onChange={(e) => setApiHash(e.target.value)} /></label>
      <label className="text-xs">Numero Telegram (+ prefisso) <input type="tel" className="mt-1 block w-full rounded border p-2" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
      <Button disabled={!apiId || !apiHash || !phone || start.isPending} onClick={() => start.mutate()}>Invia codice</Button>
      {start.isSuccess && <>
        <label className="text-xs">Codice ricevuto <input className="mt-1 block w-full rounded border p-2" value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <label className="text-xs">Password 2FA (se richiesta) <input type="password" className="mt-1 block w-full rounded border p-2" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <Button disabled={!code || finish.isPending} onClick={() => finish.mutate()}>Collega account</Button>
      </>}
      {start.isError && <Alert tone="danger">{errorMessage(start.error)}</Alert>}
      {finish.isError && <Alert tone="danger">{errorMessage(finish.error)}</Alert>}
    </>}
  </Card>
}

function GroupCard({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  return (
    <Card className="flex flex-col gap-3 p-5" role="region" aria-labelledby="bot-group-title">
      <h2 id="bot-group-title" className="text-base font-bold">
        Gruppo
      </h2>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Chat ID</dt>
        <dd>
          <RevealableValue field="chat_id" preview={tg.chat_id_preview} />
        </dd>
        <dt className="text-muted-foreground">Token del bot</dt>
        <dd>
          <RevealableValue field="bot_token" preview={tg.bot_token_preview} />
        </dd>
      </dl>
      {(!tg.bot_token_set || !tg.chat_id_set) && (
        <Alert tone="warning">
          Il bot non è configurato del tutto. <Link to={SETTINGS_LINK} className="underline">Completa token e Chat ID</Link>.
        </Alert>
      )}
    </Card>
  )
}

function TopicsCard({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  const topics = Object.entries(tg.topics).sort(([a], [b]) => a.localeCompare(b))
  const ready = tg.bot_token_set && tg.chat_id_set
  return (
    <Card className="flex flex-col gap-3 p-5" role="region" aria-labelledby="bot-topics-title">
      <h2 id="bot-topics-title" className="text-base font-bold">
        Topic per materia
      </h2>
      {topics.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nessun topic assegnato: le notifiche vanno nel topic Generale.{' '}
          <Link to={SETTINGS_LINK} className="underline">
            Assegna i topic
          </Link>
          .
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Topic per materia">
          {topics.map(([materia, id]) => (
            <BotTopic key={materia} materia={materia} id={id} name={tg.topic_names?.[String(id)]} ready={ready} />
          ))}
        </ul>
      )}
      {tg.misc_topic_id != null && <p className="text-xs text-muted-foreground">Topic generale per le altre materie: {tg.misc_topic_id}</p>}
    </Card>
  )
}

function BotTopic({ materia, id, name, ready }: { materia: string; id: number; name?: string; ready: boolean }) {
  const test = useTopicTest(String(id), materia)
  const [open, setOpen] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const client = useQueryClient()
  const recreate = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/recreate-topic', {
    body: { topic_id: id, name: name ?? '', confirmation },
  })), onSuccess: () => { setOpen(false); void client.invalidateQueries({ queryKey: ['settings'] }) } })
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-2" data-testid="bot-topic">
      <div className="text-sm">
        <p className="font-semibold">{materia}</p>
        <p className="text-xs text-muted-foreground">
          Topic {id}
          {name ? ` · «${name}»` : ''}
        </p>
        <TopicTestResult state={test} />
      </div>
      {ready && <div className="flex gap-2"><TopicTestButton state={test} label={materia} />
        {id !== 1 && name && <Button variant="outline" size="sm" onClick={() => { setConfirmation(''); setOpen(true) }}>Svuota topic</Button>}
      </div>}
      <ConfirmDialog open={open} title={`Svuota «${name}»`} confirmLabel="Elimina e ricrea"
        confirmDisabled={confirmation !== 'confermo' || recreate.isPending} onCancel={() => setOpen(false)} onConfirm={() => recreate.mutate()}>
        <p>Telegram eliminerà definitivamente il topic {id} e tutti i messaggi. RT ne creerà uno nuovo con lo stesso nome e aggiornerà l'ID. I vecchi link non funzioneranno più.</p>
        <label className="mt-3 block" htmlFor={`confirm-topic-${id}`}>Scrivi confermo</label>
        <input id={`confirm-topic-${id}`} className="mt-1 w-full rounded border p-2" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
        {recreate.isError && <Alert tone="danger">{errorMessage(recreate.error)}</Alert>}
      </ConfirmDialog>
    </li>
  )
}

const KIND_LABEL: Record<string, string> = { lezione_pronta: 'Lezione pronta', issue: 'Issue', prova: 'Prova' }

function NotificationsCard() {
  const notifications = useTelegramNotifications()
  return (
    <Card className="flex flex-col gap-3 p-5" role="region" aria-labelledby="bot-notifications-title">
      <h2 id="bot-notifications-title" className="text-base font-bold">
        Ultime notifiche inviate
      </h2>
      {notifications.isError && <Alert tone="danger">{errorMessage(notifications.error)}</Alert>}
      {notifications.data?.length === 0 && <p className="text-sm text-muted-foreground">Ancora nessuna notifica inviata.</p>}
      {!!notifications.data?.length && (
        <ul className="flex flex-col divide-y text-sm" aria-label="Notifiche">
          {notifications.data.map((n, i) => (
            <li key={`${n.sent_at}-${i}`} className="flex flex-col gap-0.5 py-2" data-testid="bot-notification">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
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
    </Card>
  )
}

/** Il pannello di avvio sta anche nelle impostazioni (RT4-F5); qui la pagina completa (RT4-FA6). */
export const telegramArea: Area = {
  routes: [{ path: 'bot', element: <TelegramPage /> }],
  nav: [{ to: '/bot', label: 'Bot Telegram', icon: Bot }],
}
