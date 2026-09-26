import { Bot } from 'lucide-react'
import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useSettings, useTopicTest, type Settings } from '@/api/settings'
import { useTelegramNotifications } from '@/api/telegram'
import { RevealableValue, TopicTestButton, TopicTestResult } from '@/components/settings/telegram'
import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { formatDateTime } from '@/lib/format'
import type { Area } from './types'

const SETTINGS_LINK = '/impostazioni#telegram'

function TelegramPage() {
  const settings = useSettings()
  return (
    <section className="flex max-w-3xl flex-col gap-4">
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
      {settings.data && <TopicsCard settings={settings.data} />}
      <NotificationsCard />
    </section>
  )
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
      {ready && <TopicTestButton state={test} label={materia} />}
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
