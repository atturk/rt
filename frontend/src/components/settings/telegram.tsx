import { Eye, EyeOff, Link2, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useFindTelegramChat, useRevealTelegram, useSetTelegramEnabled, useSetTelegramNotify, type Settings } from '@/api/settings'
import { useClearTelegramNotifications, useTelegramNotifications, useTelegramTest } from '@/api/telegram'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SecretInput } from '@/components/ui/secret-input'
import { Tooltip } from '@/components/ui/tooltip'
import { formatDateTime } from '@/lib/format'
import { ExtraSecretDelete } from './keys'
import { SecretBadge, SettingsGroup, SettingsRow, SettingsSwitch } from './ui'

/** Notifiche Telegram nella chat personale: token del bot, chat trovata dopo /start, prova e
 * ultime notifiche inviate. Nessun bot sempre acceso: RT manda solo messaggi. */

const FIELD_LABEL = { bot_token: 'token del bot', chat_id: 'Chat ID' } as const

/**
 * Anteprima parzialmente nascosta (1234…wXyZ) con il pulsante occhio. Il valore completo arriva
 * dall'API solo quando si preme l'occhio e resta solo in questa vista finché non la si nasconde.
 */
export function RevealableValue({ field, preview }: { field: 'bot_token' | 'chat_id'; preview: string | null | undefined }) {
  const reveal = useRevealTelegram()
  const [shown, setShown] = useState(false)
  const label = FIELD_LABEL[field]
  if (!preview) return <SecretBadge set={false} />
  const value = shown && reveal.data ? (reveal.data.value ?? '') : preview
  function toggle() {
    if (shown) {
      setShown(false)
      reveal.reset()
      return
    }
    reveal.mutate(field, { onSuccess: () => setShown(true) })
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <code className="break-all rounded bg-muted px-1.5 py-0.5 text-meta" data-testid={`${field}-value`}>
        {value}
      </code>
      <Button
        variant="ghost"
        size="icon"
        className="size-7"
        aria-label={shown ? `Nascondi ${label}` : `Mostra ${label}`}
        aria-pressed={shown}
        onClick={toggle}
        disabled={reveal.isPending}
      >
        {shown ? <EyeOff /> : <Eye />}
      </Button>
      {reveal.isError && <span className="text-danger">{errorMessage(reveal.error)}</span>}
    </span>
  )
}

/** Interruttore delle notifiche (spente di predefinito). */
export function TelegramEnabledToggle({ enabled }: { enabled: boolean }) {
  const set = useSetTelegramEnabled()
  // Subito al clic; se il salvataggio non riesce torna il valore delle impostazioni.
  const shown = set.isPending ? (set.variables ?? enabled) : enabled
  return (
    <div data-testid="telegram-enabled">
      <SettingsSwitch
        id="telegram-enabled"
        label="Ricevi le notifiche su Telegram"
        checked={shown}
        disabled={set.isPending}
        onChange={next => set.mutate(next)}
      />
      {set.isError && (
        <div className="px-4 pb-3">
          <Alert tone="danger">{errorMessage(set.error)}</Alert>
        </div>
      )}
    </div>
  )
}

export function TelegramSection({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  return (
    <>
      <SettingsGroup
        id="telegram"
        title="Telegram"
        description="RT ti scrive quando una lezione è pronta, quando la scaletta o le issue aspettano una tua decisione e quando una lavorazione non riesce."
      >
        <TelegramEnabledToggle enabled={tg.enabled ?? false} />
        {tg.enabled && <TelegramChatSetup settings={settings} />}
      </SettingsGroup>
      {tg.enabled && <TelegramNotifyEvents settings={settings} />}
    </>
  )
}

const NOTIFY_EVENTS: { key: string; label: string; example: string }[] = [
  {
    key: 'lezione_pronta',
    label: 'Una lezione è pronta',
    example: '✅ Lezione pronta\n📘 Biochimica — Lipidi\n📅 2026-10-12 · BIOCHIMICA',
  },
  {
    key: 'verifica_pronta',
    label: 'La verifica è completata',
    example: '🔎 Verifica completata\n📘 Biochimica — Lipidi\n3 issue da decidere in RT',
  },
  {
    key: 'scaletta_da_approvare',
    label: 'La scaletta aspetta la tua approvazione',
    example: '📝 Scaletta da approvare\n📘 Biochimica — Lipidi\nAprila in RT per approvarla o chiedere modifiche.',
  },
  {
    key: 'issue_da_decidere',
    label: 'Ci sono issue da decidere',
    example: '🔎 Issue da decidere (3)\n📘 Biochimica — Lipidi\nDecidile in RT: dopo la lezione si completa da sola.',
  },
  {
    key: 'errore',
    label: 'Una lavorazione non riesce',
    example: '❌ Lavorazione non riuscita\n📘 Biochimica — Lipidi\nDettaglio dell’errore',
  },
]

const DEFAULT_NOTIFY: Record<string, boolean> = {
  lezione_pronta: true,
  verifica_pronta: true,
  errore: true,
  scaletta_da_approvare: true,
  issue_da_decidere: true,
}

function TelegramChatSetup({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  const [token, setToken] = useState('')
  const find = useFindTelegramChat()
  const test = useTelegramTest()
  const canFind = !!token.trim() || tg.bot_token_set

  return (
    <>
      <div className="px-4 py-3">
        <ol className="list-decimal space-y-1 pl-5 text-body text-muted-foreground">
          <li>
            Su Telegram apri <strong className="text-foreground">@BotFather</strong>, crea un bot con <code>/newbot</code> e copia il token che ti dà.
          </li>
          <li>Incollalo qui sotto.</li>
          <li>
            Apri il tuo bot e scrivigli <code>/start</code>.
          </li>
          <li>Premi «Collega la chat».</li>
        </ol>
      </div>
      <SettingsRow
        label="Token del bot"
        htmlFor="tg-token"
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            <span>Token salvato:</span>
            <RevealableValue field="bot_token" preview={tg.bot_token_preview} />
            <ExtraSecretDelete name="RT_TELEGRAM_BOT_TOKEN" label="token del bot" set={tg.bot_token_set} />
          </span>
        }
        control={
          <div className="w-full @sm:w-60">
            <SecretInput
              id="tg-token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={tg.bot_token_set ? 'Lascia vuoto per mantenere quello salvato' : '123456:ABC…'}
            />
          </div>
        }
      />
      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => find.mutate({ bot_token: token.trim() || null }, { onSuccess: (r) => r.found && setToken('') })} disabled={!canFind || find.isPending}>
            <Link2 /> Collega la chat
          </Button>
          <Button
            variant="outline"
            onClick={() => test.mutate()}
            disabled={!tg.bot_token_set || !tg.chat_id_set || test.isPending}
          >
            <Send /> Manda un messaggio di prova
          </Button>
        </div>
        <p className="text-meta text-muted-foreground" data-testid="telegram-chat">
          {tg.chat_id_set ? (
            <>
              Chat collegata: <RevealableValue field="chat_id" preview={tg.chat_id_preview} />
            </>
          ) : (
            'Nessuna chat collegata.'
          )}
        </p>
        {find.isError && <Alert tone="danger">{errorMessage(find.error)}</Alert>}
        {find.data && (
          <p role="status" className={find.data.found ? 'text-meta text-success' : 'text-meta text-warning'} data-testid="telegram-chat-result">
            {find.data.message}
          </p>
        )}
        {test.isError && <Alert tone="danger">{errorMessage(test.error)}</Alert>}
        {test.data && (
          <p role="status" className={test.data.ok ? 'text-meta text-success' : 'text-meta text-danger'} data-testid="telegram-test-result">
            {test.data.message}
          </p>
        )}
      </div>
    </>
  )
}

function TelegramNotifyEvents({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  const saveNotify = useSetTelegramNotify()
  const notify = { ...DEFAULT_NOTIFY, ...(tg.notify ?? {}) }

  return (
    <SettingsGroup id="telegram-eventi" title="Ricevi una notifica quando…">
      <div className="divide-y divide-border/60" data-testid="telegram-notify-events">
        {NOTIFY_EVENTS.map((ev) => {
          const baseChecked = notify[ev.key] ?? true
          const shown = saveNotify.isPending && saveNotify.variables && ev.key in saveNotify.variables
            ? saveNotify.variables[ev.key]
            : baseChecked
          return (
            <SettingsSwitch
              key={ev.key}
              id={`tg-notify-${ev.key}`}
              label={ev.label}
              info={<span className="whitespace-pre-line">{ev.example}</span>}
              checked={shown}
              disabled={saveNotify.isPending}
              onChange={v => saveNotify.mutate({ ...notify, [ev.key]: v })}
            />
          )
        })}
      </div>
      {saveNotify.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(saveNotify.error)}</Alert>
        </div>
      )}
    </SettingsGroup>
  )
}

const KIND_LABEL: Record<string, string> = {
  lezione_pronta: 'Lezione pronta',
  verifica_pronta: 'Verifica completata',
  scaletta_da_approvare: 'Scaletta da approvare',
  issue_da_decidere: 'Issue da decidere',
  decisione: 'Decisione',
  errore: 'Errore',
  prova: 'Prova',
}

export function NotificationsCard() {
  const notifications = useTelegramNotifications()
  const clear = useClearTelegramNotifications()
  const clearAction = notifications.data?.length ? (
    <Tooltip content="Svuota l'elenco: i messaggi su Telegram restano">
      {props => (
        <Button
          {...props}
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground hover:text-foreground"
          aria-label="Svuota l'elenco"
          disabled={clear.isPending}
          onClick={() => clear.mutate()}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </Button>
      )}
    </Tooltip>
  ) : null

  return (
    <SettingsGroup id="notifiche-telegram" title="Ultime notifiche inviate" headerAction={clearAction}>
      {clear.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(clear.error)}</Alert>
        </div>
      )}
      {notifications.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(notifications.error)}</Alert>
        </div>
      )}
      {notifications.data?.length === 0 && (
        <p className="px-4 py-3 text-body text-muted-foreground">Nessuna notifica.</p>
      )}
      {!!notifications.data?.length && (
        <ul className="divide-y divide-border/60 text-body" aria-label="Notifiche">
          {notifications.data.map((n, i) => (
            <li key={`${n.sent_at}-${i}`} className="flex flex-col gap-0.5 px-4 py-3" data-testid="bot-notification">
              <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground">
                <Badge tone={n.ok ? 'neutral' : 'danger'}>{KIND_LABEL[n.kind] ?? n.kind}</Badge>
                <time dateTime={n.sent_at}>{formatDateTime(n.sent_at)}</time>
                {!n.ok && <span className="text-danger">non inviata</span>}
              </div>
              <p className="whitespace-pre-line">{n.text}</p>
            </li>
          ))}
        </ul>
      )}
    </SettingsGroup>
  )
}
