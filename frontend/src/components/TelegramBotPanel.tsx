import { Play, Square } from 'lucide-react'

import { ApiError, errorMessage } from '@/api/client'
import { useTelegramDaemon, useTelegramDaemonAction } from '@/api/telegram'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/**
 * Stato del bot Telegram con avvio e arresto (come 'rt telegram-daemon'). Il bot gira come
 * processo proprio: resta attivo anche chiudendo RT. Pensato per stare nelle impostazioni.
 */
export function TelegramBotPanel() {
  const daemon = useTelegramDaemon()
  const action = useTelegramDaemonAction()
  const running = daemon.data?.running ?? false
  const notConfigured = action.error instanceof ApiError && action.error.code === 'telegram_not_configured'
  return (
    <Card className="flex flex-col gap-3 p-5" aria-labelledby="telegram-bot-title" data-testid="telegram-bot" data-running={running}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="telegram-bot-title" className="mr-auto text-base font-bold">
          Bot Telegram
        </h2>
        {daemon.isSuccess && (
          <Badge tone={running ? 'success' : 'neutral'} role="status">
            {running ? `Attivo (pid ${daemon.data.pid})` : 'Fermo'}
          </Badge>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Il bot manda le lezioni, le issue da rivedere e il recall su Telegram. Parte come processo a sé: resta attivo anche se chiudi RT.
      </p>
      {daemon.isError && <Alert tone="danger">{errorMessage(daemon.error)}</Alert>}
      {notConfigured ? (
        <Alert tone="warning">Salva prima token e Chat ID del bot nelle impostazioni di Telegram.</Alert>
      ) : (
        action.isError && <Alert tone="danger">{errorMessage(action.error)}</Alert>
      )}
      <div className="flex gap-2">
        {running ? (
          <Button variant="outline" onClick={() => action.mutate('stop')} disabled={action.isPending}>
            <Square /> Ferma il bot
          </Button>
        ) : (
          <Button onClick={() => action.mutate('start')} disabled={action.isPending || daemon.isPending}>
            <Play /> Avvia il bot
          </Button>
        )}
      </div>
    </Card>
  )
}
