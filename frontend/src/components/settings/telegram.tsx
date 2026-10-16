import { Eye, EyeOff, Link2, Send } from 'lucide-react'
import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useFindTelegramChat, useRevealTelegram, useSetTelegramEnabled, type Settings } from '@/api/settings'
import { useTelegramNotifications, useTelegramTest } from '@/api/telegram'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SecretInput } from '@/components/ui/secret-input'
import { formatDateTime } from '@/lib/format'
import { Checkbox, Field, SecretBadge, Section } from './common'
import { ExtraSecretDelete } from './keys'

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
    <div className="flex flex-col gap-1" data-testid="telegram-enabled">
      <Checkbox id="telegram-enabled" label="Ricevi le notifiche su Telegram" checked={shown} disabled={set.isPending} onChange={enabled => set.mutate(enabled)} />
      {set.isError && <Alert tone="danger">{errorMessage(set.error)}</Alert>}
    </div>
  )
}

export function TelegramSection({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  return (
    <Section id="telegram" title="Telegram">
      <p className="text-body text-muted-foreground">
        RT ti scrive quando una lezione è pronta, quando la scaletta o le issue aspettano una tua decisione e quando una lavorazione non
        riesce.
      </p>
      <TelegramEnabledToggle enabled={tg.enabled ?? false} />
      {tg.enabled && <TelegramChatSetup key={`${tg.bot_token_preview}-${tg.chat_id_preview}`} settings={settings} />}
    </Section>
  )
}

function TelegramChatSetup({ settings }: { settings: Settings }) {
  const tg = settings.telegram
  const [token, setToken] = useState('')
  const find = useFindTelegramChat()
  const test = useTelegramTest()
  const canFind = !!token.trim() || tg.bot_token_set
  return (
    <div className="flex flex-col gap-3">
      <ol className="list-decimal pl-5 text-body">
        <li>
          Su Telegram apri <strong>@BotFather</strong>, crea un bot con <code>/newbot</code> e copia il token che ti dà.
        </li>
        <li>Incollalo qui sotto.</li>
        <li>
          Apri il tuo bot e scrivigli <code>/start</code>.
        </li>
        <li>Premi «Collega la chat».</li>
      </ol>
      <Field
        label="Token del bot"
        htmlFor="tg-token"
        hint={
          <>
            Token salvato: <RevealableValue field="bot_token" preview={tg.bot_token_preview} />
            <ExtraSecretDelete name="RT_TELEGRAM_BOT_TOKEN" label="token del bot" set={tg.bot_token_set} />
          </>
        }
      >
        <SecretInput
          id="tg-token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={tg.bot_token_set ? 'Lascia vuoto per mantenere quello salvato' : '123456:ABC…'}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => find.mutate({ bot_token: token.trim() || null })} disabled={!canFind || find.isPending}>
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
  )
}

const KIND_LABEL: Record<string, string> = { lezione_pronta: 'Lezione pronta', decisione: 'Decisione', errore: 'Errore', prova: 'Prova' }

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
