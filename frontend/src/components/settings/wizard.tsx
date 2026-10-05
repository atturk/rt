import { Check } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useDismissNotice } from '@/api/documentEdit'
import { useAssignAllPhases, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SettingsSelect as Select } from './common'
import { cn } from '@/lib/utils'
import { Field } from './common'
import { ModelTest, NewConnectionForm, PhaseRows } from './models'

/** Configurazione guidata del primo avvio (RT4-F5): ogni passo salva subito sul backend e
 * il passo corrente sta nell'URL, così una ricarica riprende da dove si era. */

const STEPS = ['Connessione', 'Modelli', 'Telegram', 'Fatto'] as const

function stepDone(settings: Settings, index: number): boolean {
  switch (index) {
    case 0:
      return settings.connections.length > 0
    case 1:
      return settings.phases.every((p) => !!p.model)
    case 2:
      return settings.telegram.bot_token_set && settings.telegram.chat_id_set
    default:
      return false
  }
}

export function SetupWizard({ settings }: { settings: Settings }) {
  const [params, setParams] = useSearchParams()
  const requested = Number(params.get('passo') ?? '1')
  const step = Math.min(Math.max(1, Number.isFinite(requested) ? requested : 1), STEPS.length)
  const go = (n: number) => setParams({ passo: String(n) })
  const next = () => go(step + 1)
  const navigate = useNavigate()
  const dismiss = useDismissNotice()
  // Senza connessioni ogni pagina porta qui (setup_required): "Configura dopo" lo spegne.
  const later = () => dismiss.mutate('setup_wizard', { onSuccess: () => void navigate('/') })

  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-bold tracking-tight">Configurazione guidata</h1>
        </div>
        {settings.setup_required && (
          <Button variant="outline" size="sm" onClick={later} disabled={dismiss.isPending}>
            Configura dopo
          </Button>
        )}
      </div>
      <ol className="flex flex-wrap gap-2 text-meta" aria-label="Passi">
        {STEPS.map((label, i) => (
          <li key={label}>
            <button
              type="button"
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
        <h2 className="mb-3 text-body font-bold">{STEPS[step - 1]}</h2>
        {step === 1 && (
          <div className="flex flex-col gap-3">
            {settings.connections.length > 0 ? (
              <>
                <p className="text-body">
                  Connessioni già configurate: <strong>{settings.connections.map((c) => c.name).join(', ')}</strong>. Puoi aggiungerne
                  un'altra o continuare.
                </p>
                <div>
                  <Button onClick={next}>Continua</Button>
                </div>
                <details>
                  <summary className="cursor-pointer text-body">Aggiungi un'altra connessione</summary>
                  <div className="mt-3">
                    <NewConnectionForm onCreated={() => go(2)} submitLabel="Crea e continua" />
                  </div>
                </details>
              </>
            ) : (
              <>
                <p className="text-body text-muted-foreground">
                  Una connessione è un provider LLM (OpenRouter, Google AI Studio, DeepSeek o un server compatibile) con la tua chiave API.
                </p>
                <NewConnectionForm onCreated={() => go(2)} submitLabel="Crea e continua" />
              </>
            )}
          </div>
        )}
        {step === 2 && <ModelsStep settings={settings} onDone={next} />}
        {step === 3 && <TelegramStep settings={settings} onDone={next} />}
        {step === 4 && (
          <div className="flex flex-col gap-3 text-body">
            <ul className="flex flex-col gap-1">
              {STEPS.slice(0, 3).map((label, i) => (
                <li key={label} className="flex items-center gap-2">
                  {stepDone(settings, i) ? <Check className="size-4 text-success" aria-hidden /> : <span className="size-4 text-center">–</span>}
                  {label}
                  {!stepDone(settings, i) && <span className="text-meta text-muted-foreground">{i === 2 ? '(facoltativo)' : 'da completare'}</span>}
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <Link to="/" className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-body font-medium text-primary-foreground">
                Vai alle lezioni
              </Link>
              <Link to="/impostazioni" className="inline-flex h-9 items-center rounded-md border px-4 text-body">
                Tutte le impostazioni
              </Link>
            </div>
          </div>
        )}
      </Card>
    </section>
  )
}

/** Modelli: di norma uno solo per le fasi testuali; "Scegli per ogni fase" mostra le righe
 * della pagina Modelli. La scelta sta nell'URL (?modelli=per-fase), così resta dopo la ricarica. */
function ModelsStep({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const [params, setParams] = useSearchParams()
  // Stato locale per il radio controllato, copiato nell'URL (che si aggiorna con una navigazione).
  const [perPhase, setPerPhase] = useState(params.get('modelli') === 'per-fase')
  function setMode(next: boolean) {
    setPerPhase(next)
    const updated = new URLSearchParams(params)
    if (next) updated.set('modelli', 'per-fase')
    else updated.delete('modelli')
    setParams(updated, { replace: true })
  }

  if (settings.connections.length === 0) return <Alert tone="warning">Crea prima una connessione nel passo precedente.</Alert>
  return (
    <div className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-1.5">
        <legend className="sr-only">Come scegliere i modelli</legend>
        <label className="inline-flex items-center gap-2 text-body">
          <input type="radio" name="wizard-models-mode" className="size-4 accent-current" checked={!perPhase} onChange={() => setMode(false)} />
          Usa lo stesso modello per tutte le fasi
        </label>
        <label className="inline-flex items-center gap-2 text-body">
          <input type="radio" name="wizard-models-mode" className="size-4 accent-current" checked={perPhase} onChange={() => setMode(true)} />
          Scegli per ogni fase
        </label>
      </fieldset>
      {perPhase ? (
        <div className="flex flex-col gap-3">
          <p className="text-body text-muted-foreground">Ogni fase si salva con il suo pulsante; Prova fa una chiamata minima prima di salvare.</p>
          <PhaseRows settings={settings} />
          {stepDone(settings, 1) ? (
            <div>
              <Button onClick={onDone}>Continua</Button>
            </div>
          ) : (
            <p className="text-meta text-muted-foreground">Assegna un modello a tutte le fasi per continuare.</p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4"><SameModelForm settings={settings} onDone={onDone} /><PhaseRows settings={{ ...settings, phases: settings.phases.filter(p => ['image_description', 'enrichment_image'].includes(p.job)) }} /></div>
      )}
    </div>
  )
}

function SameModelForm({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const assign = useAssignAllPhases()
  const first = settings.phases.find((p) => p.connection) ?? null
  const [connection, setConnection] = useState(first?.connection ?? settings.connections[0]?.name ?? '')
  const [model, setModel] = useState(first?.model ?? '')
  const models = settings.connections.find((c) => c.name === connection)?.models ?? []
  const pending = assign.isPending
  const error = assign.isError ? errorMessage(assign.error) : null

  function submit(e: FormEvent) {
    e.preventDefault()
    assign.mutate({ jobs: settings.phases.filter(p => !['image_description', 'enrichment_image'].includes(p.job)).map(p => p.job), connection, model: model.trim() })
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label="Stesso modello per tutte le fasi">
      <p className="text-body text-muted-foreground">Descrizione immagini e generazione immagini richiedono modelli dedicati: sceglili a parte.</p>
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
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex flex-wrap items-start gap-2">
        <Button type="submit" disabled={pending || !connection || !model.trim()}>
          Usa per tutte le fasi
        </Button>
        <ModelTest connection={connection} model={model} className="contents" resultClassName="order-last basis-full" />
        {stepDone(settings, 1) && (
          <Button variant="outline" onClick={onDone}>
            Continua
          </Button>
        )}
      </div>
    </form>
  )
}

function TelegramStep({ onDone }: { settings: Settings; onDone: () => void }) {
  return <div className="flex flex-col gap-3">
    <Link to="/impostazioni/telegram" className="text-body underline">Apri Telegram</Link>
    <Button onClick={onDone}>Continua</Button>
  </div>
}
