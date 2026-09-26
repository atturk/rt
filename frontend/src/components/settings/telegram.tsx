import { Eye, EyeOff, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useDeleteListenMessages, useListenMessages, useRevealTelegram, type useTopicTest } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { SecretBadge } from './common'

/** Pezzi di Telegram condivisi da impostazioni, configurazione guidata e pagina Bot (RT4-FA6). */

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
      <code className="break-all rounded bg-muted px-1.5 py-0.5 text-[11px]" data-testid={`${field}-value`}>
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

/** "Prova": pulsante ed esito sono separati (useTopicTest) perché nelle righe del form
 * l'esito va sotto la riga, non accanto al pulsante. */
type TopicTest = ReturnType<typeof useTopicTest>

export function TopicTestButton({ state, label }: { state: TopicTest; label: string }) {
  return (
    <Button variant="outline" size="sm" className="h-9" aria-label={`Prova ${label}`} disabled={!state.valid || state.test.isPending} onClick={state.run}>
      <Send /> Prova
    </Button>
  )
}

export function TopicTestResult({ state }: { state: TopicTest }) {
  const { test } = state
  if (test.isError)
    return (
      <p role="alert" className="text-[11px] text-danger" data-testid="topic-test-result">
        {errorMessage(test.error)}
      </p>
    )
  if (!test.data) return null
  return (
    <p role="status" className={test.data.ok ? 'text-[11px] text-success' : 'text-[11px] text-danger'} data-testid="topic-test-result">
      {test.data.message}
    </p>
  )
}

/** "Cancella i messaggi di rilevamento": solo quelli ricevuti durante l'ultimo ascolto, dopo conferma. */
export function ListenCleanup({ enabled }: { enabled: boolean }) {
  const info = useListenMessages(enabled)
  const del = useDeleteListenMessages()
  const [confirming, setConfirming] = useState(false)
  const count = info.data?.count ?? 0
  const available = enabled && count > 0 && !info.data?.cleaned
  return (
    <div className="flex flex-col gap-2">
      {!confirming ? (
        <div>
          <Button variant="outline" onClick={() => setConfirming(true)} disabled={!available || del.isPending}>
            <Trash2 /> Cancella i messaggi di rilevamento
          </Button>
        </div>
      ) : (
        <div role="group" aria-label="Conferma cancellazione" className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
          <p>
            Eliminare dal gruppo {count === 1 ? "il messaggio ricevuto" : `i ${count} messaggi ricevuti`} durante l'ultimo ascolto dei topic?
            Gli altri messaggi del gruppo non vengono toccati.
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              onClick={() => del.mutate(undefined, { onSettled: () => setConfirming(false) })}
              disabled={del.isPending}
            >
              Sì, cancella
            </Button>
            <Button variant="outline" size="sm" onClick={() => setConfirming(false)} disabled={del.isPending}>
              Annulla
            </Button>
          </div>
        </div>
      )}
      {del.isError && <Alert tone="danger">{errorMessage(del.error)}</Alert>}
      {del.data && (
        <div role="status" className="text-xs" data-testid="cleanup-result">
          <p className="text-success">
            {del.data.deleted === 1 ? 'Eliminato 1 messaggio.' : `Eliminati ${del.data.deleted} messaggi.`}
          </p>
          {del.data.failed.length > 0 && (
            <>
              <p className="text-warning">Non eliminati: {del.data.failed.length}</p>
              <ul className="list-disc pl-5 text-muted-foreground">
                {del.data.failed.map((f) => (
                  <li key={f.message_id}>
                    Messaggio {f.message_id}: {f.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {!del.data && info.data?.cleaned && count > 0 && (
        <p className="text-[11px] text-muted-foreground">I messaggi dell'ultimo ascolto sono già stati cancellati.</p>
      )}
    </div>
  )
}
