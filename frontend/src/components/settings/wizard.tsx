import { Check } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useAssignAllPhases, useSaveTelegram, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { Field, SecretBadge } from './common'
import { LessonsRootForm } from './general'
import { NewConnectionForm } from './models'

/** Configurazione guidata del primo avvio (RT4-F5): ogni passo salva subito sul backend e
 * il passo corrente sta nell'URL, così una ricarica riprende da dove si era. */

const STEPS = ['Cartella dati', 'Connessione', 'Modelli', 'Telegram', 'Fatto'] as const

function stepDone(settings: Settings, index: number): boolean {
  switch (index) {
    case 0:
      return !settings.setup_required
    case 1:
      return settings.connections.length > 0
    case 2:
      return settings.phases.every((p) => !!p.model)
    case 3:
      return settings.telegram.bot_token_set && !!settings.telegram.chat_id
    default:
      return false
  }
}

export function SetupWizard({ settings }: { settings: Settings }) {
  const [params, setParams] = useSearchParams()
  const requested = Number(params.get('passo') ?? '1')
  // Senza cartella dati non si va avanti: il resto della configurazione vive lì dentro.
  const step = settings.setup_required ? 1 : Math.min(Math.max(1, Number.isFinite(requested) ? requested : 1), STEPS.length)
  const go = (n: number) => setParams({ passo: String(n) })
  const next = () => go(step + 1)

  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Configurazione guidata</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pochi passi per iniziare. Puoi cambiare tutto in seguito dalle impostazioni.
        </p>
      </div>
      <ol className="flex flex-wrap gap-2 text-xs" aria-label="Passi">
        {STEPS.map((label, i) => (
          <li key={label}>
            <button
              type="button"
              disabled={settings.setup_required && i > 0}
              onClick={() => go(i + 1)}
              aria-current={step === i + 1 ? 'step' : undefined}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 disabled:opacity-50',
                step === i + 1 ? 'border-foreground font-semibold' : 'text-muted-foreground',
              )}
            >
              {stepDone(settings, i) ? <Check className="size-3.5 text-success" aria-label="completato" /> : <span>{i + 1}.</span>}
              {label}
            </button>
          </li>
        ))}
      </ol>

      <Card className="p-5">
        <h2 className="mb-3 text-base font-bold">{STEPS[step - 1]}</h2>
        {step === 1 && (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              Scegli dove RT tiene le lezioni. Nella stessa cartella stanno il database (<code>.rt/rt.db</code>) e i file audio e immagini
              (<code>.rt/media/</code>).
            </p>
            <LessonsRootForm settings={settings} onSaved={() => go(2)} submitLabel="Salva e continua" />
          </div>
        )}
        {step === 2 && (
          <div className="flex flex-col gap-3">
            {settings.connections.length > 0 ? (
              <>
                <p className="text-sm">
                  Connessioni già configurate: <strong>{settings.connections.map((c) => c.name).join(', ')}</strong>. Puoi aggiungerne
                  un'altra o continuare.
                </p>
                <div>
                  <Button onClick={next}>Continua</Button>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm">Aggiungi un'altra connessione</summary>
                  <div className="mt-3">
                    <NewConnectionForm onCreated={() => go(3)} submitLabel="Crea e continua" />
                  </div>
                </details>
              </>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  Una connessione è un provider LLM (OpenRouter, Google AI Studio, DeepSeek o un server compatibile) con la tua chiave API.
                </p>
                <NewConnectionForm onCreated={() => go(3)} submitLabel="Crea e continua" />
              </>
            )}
          </div>
        )}
        {step === 3 && <ModelsStep settings={settings} onDone={next} />}
        {step === 4 && <TelegramStep settings={settings} onDone={next} />}
        {step === 5 && (
          <div className="flex flex-col gap-3 text-sm">
            <ul className="flex flex-col gap-1">
              {STEPS.slice(0, 4).map((label, i) => (
                <li key={label} className="flex items-center gap-2">
                  {stepDone(settings, i) ? <Check className="size-4 text-success" aria-hidden /> : <span className="size-4 text-center">–</span>}
                  {label}
                  {!stepDone(settings, i) && <span className="text-xs text-muted-foreground">{i === 3 ? '(facoltativo)' : 'da completare'}</span>}
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <Link to="/" className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground">
                Vai alle lezioni
              </Link>
              <Link to="/impostazioni" className="inline-flex h-9 items-center rounded-md border px-4 text-sm">
                Tutte le impostazioni
              </Link>
            </div>
          </div>
        )}
      </Card>
    </section>
  )
}

/** Un modello per tutte le sei fasi; per differenziarle c'è la pagina Modelli. */
function ModelsStep({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const assign = useAssignAllPhases()
  const first = settings.phases.find((p) => p.connection) ?? null
  const [connection, setConnection] = useState(first?.connection ?? settings.connections[0]?.name ?? '')
  const [model, setModel] = useState(first?.model ?? '')
  const models = settings.connections.find((c) => c.name === connection)?.models ?? []
  const pending = assign.isPending
  const error = assign.isError ? errorMessage(assign.error) : null

  function submit(e: FormEvent) {
    e.preventDefault()
    assign.mutate({ jobs: settings.phases.map((p) => p.job), connection, model: model.trim() }, { onSuccess: onDone })
  }

  if (settings.connections.length === 0) return <Alert tone="warning">Crea prima una connessione nel passo precedente.</Alert>
  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <p className="text-sm text-muted-foreground">Il modello scelto viene usato per outline, rewrite, review, recall e immagini.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Connessione" htmlFor="wizard-connection">
          <Select id="wizard-connection" value={connection} onChange={(e) => setConnection(e.target.value)}>
            {settings.connections.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Modello" htmlFor="wizard-model">
          <Input id="wizard-model" list="wizard-models" value={model} placeholder="es. deepseek/deepseek-v4-flash" onChange={(e) => setModel(e.target.value)} />
          <datalist id="wizard-models">
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </Field>
      </div>
      <ul className="text-xs text-muted-foreground" aria-label="Modelli salvati">
        {settings.phases.map((p) => (
          <li key={p.job}>
            {p.label}: {p.model ? `${p.connection} · ${p.model}` : 'non assegnato'}
          </li>
        ))}
      </ul>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending || !connection || !model.trim()}>
          Usa per tutte le fasi
        </Button>
        {stepDone(settings, 2) && (
          <Button variant="outline" onClick={onDone}>
            Continua
          </Button>
        )}
      </div>
    </form>
  )
}

function TelegramStep({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const save = useSaveTelegram()
  const tg = settings.telegram
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState(tg.chat_id ?? '')
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate(
      { bot_token: token.trim() || null, chat_id: chatId.trim() || null, topics: tg.topics, misc_topic_id: tg.misc_topic_id ?? null },
      { onSuccess: onDone },
    )
  }
  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <p className="text-sm text-muted-foreground">
        Facoltativo: il bot manda i documenti e le domande di recall nel gruppo Telegram. I topic per materia si assegnano dalle impostazioni.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Token del bot" htmlFor="wizard-tg-token" hint={<>Token: <SecretBadge set={tg.bot_token_set} /></>}>
          <Input id="wizard-tg-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <Field label="Chat ID del gruppo" htmlFor="wizard-tg-chat">
          <Input id="wizard-tg-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="-1001234567890" />
        </Field>
      </div>
      {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || (!token.trim() && !chatId.trim())}>
          Salva e continua
        </Button>
        <Button variant="outline" onClick={onDone}>
          Salta
        </Button>
      </div>
    </form>
  )
}
