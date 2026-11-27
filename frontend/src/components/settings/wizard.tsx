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
import { cn } from '@/lib/utils'
import { SettingsDisclosure, SettingsRow, SettingsSelect as Select } from './ui'
import { ModelTest, NewConnectionForm, PhaseRows } from './models'
import { CloudPanel } from './cloud'
import { useCloudStatus } from '@/api/cloud'

/** Configurazione guidata del primo avvio (RT4-F5): ogni passo salva subito sul backend e
 * il passo corrente sta nell'URL, così una ricarica riprende da dove si era. */

const STEPS = ['Connessione', 'Modello', 'Pronto'] as const
const OPTIONAL_JOBS = new Set(['image_description', 'enrichment_image', 'study_chat'])

function stepDone(settings: Settings, index: number): boolean {
  switch (index) {
    case 0:
      return settings.connections.length > 0
    case 1: {
      const required = settings.phases.filter((p) => !OPTIONAL_JOBS.has(p.job))
      return required.length > 0 && required.every((p) => !!p.model)
    }
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
  const later = () => {
    if (!settings.notices.dismissed.includes('setup_wizard')) {
      dismiss.mutate('setup_wizard', { onSettled: () => void navigate('/') })
    } else {
      void navigate('/')
    }
  }
  const existingNames = settings.connections.map((c) => c.name)

  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-bold tracking-tight">Configurazione guidata</h1>
        </div>
        {step < STEPS.length && (
          <Button variant="ghost" size="sm" onClick={later} disabled={dismiss.isPending} className="text-link hover:underline">
            Configura dopo
          </Button>
        )}
      </div>
      <ol className="flex flex-wrap gap-2 text-meta" aria-label="Passi">
        {STEPS.map((label, i) => {
          const done = stepDone(settings, i)
          const active = step === i + 1
          return (
            <li key={label}>
              <button
                type="button"
                onClick={() => go(i + 1)}
                aria-current={active ? 'step' : undefined}
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 transition-colors cursor-pointer disabled:opacity-50',
                  active ? 'border-foreground font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <span
                  className={cn(
                    'inline-flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
                    done
                      ? 'bg-success-soft text-success'
                      : active
                        ? 'bg-foreground text-background'
                        : 'bg-muted text-muted-foreground',
                  )}
                >
                  {done ? <Check className="size-3.5" aria-label="completato" /> : <span>{i + 1}</span>}
                </span>
                {label}
              </button>
            </li>
          )
        })}
      </ol>

      <Card className="p-6">
        {step === 1 && (
          <div className="flex flex-col gap-4">
            <header className="flex flex-col gap-1">
              <h2 className="text-heading font-semibold tracking-tight">Collega un servizio di IA</h2>
              <p className="text-body text-muted-foreground">
                RT usa un servizio di intelligenza artificiale per rielaborare e verificare le lezioni. Lo paghi tu, a consumo, con la tua chiave.
              </p>
            </header>
            {settings.connections.length > 0 ? (
              <>
                <p className="text-body">
                  Connessioni già configurate: <strong>{settings.connections.map((c) => c.name).join(', ')}</strong>. Puoi aggiungerne
                  un'altra o continuare.
                </p>
                <div>
                  <Button className="h-11 px-6" onClick={next}>Continua</Button>
                </div>
                <div className="rounded-lg border">
                  <SettingsDisclosure label="Aggiungi un'altra connessione">
                    <NewConnectionForm variant="wizard" existingNames={existingNames} onCreated={() => go(2)} submitLabel="Continua" />
                  </SettingsDisclosure>
                </div>
              </>
            ) : (
              <ConnectionChoice existingNames={existingNames} onByok={() => go(2)} onCloud={() => go(3)} />
            )}
          </div>
        )}
        {step === 2 && <ModelsStep settings={settings} onDone={next} />}
        {step === 3 && (
          <div className="flex flex-col gap-3 text-body">
            <h2 className="text-heading font-semibold tracking-tight">RT è pronto</h2>
            <Link to="/" className="inline-flex h-11 w-fit items-center rounded-md bg-primary px-6 text-body font-medium text-primary-foreground">
              Vai alle lezioni
            </Link>
          </div>
        )}
      </Card>
    </section>
  )
}

/** Primo avvio senza connessioni: modalità facilitata (abbonamento RT Cloud, niente chiavi né
 * modelli) oppure BYOK con la propria chiave. Senza RT Cloud pubblicato resta solo il BYOK. */
function ConnectionChoice({
  existingNames,
  onByok,
  onCloud,
}: {
  existingNames: string[]
  onByok: () => void
  onCloud: () => void
}) {
  const cloud = useCloudStatus()
  const [mode, setMode] = useState<'cloud' | 'byok' | null>(null)
  const byok = (
    <>
      <div className="rounded-lg border border-success/30 bg-success-soft p-3.5 text-body text-foreground" data-testid="connection-explainer">
        <strong>Connessione</strong> = il servizio che usi, per esempio OpenRouter.{' '}
        <strong>Chiave API</strong> = il codice personale che quel servizio ti dà. Una connessione può avere più chiavi: RT le usa a turno e passa alla successiva se una finisce il credito o raggiunge i limiti.
      </div>
      <NewConnectionForm variant="wizard" existingNames={existingNames} onCreated={onByok} submitLabel="Continua" />
    </>
  )
  if (!cloud.data?.available) return byok
  return (
    <div className="flex flex-col gap-3">
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Come usare l'IA</legend>
        <label className="flex items-start gap-2 text-body">
          <input type="radio" name="wizard-ai-mode" className="mt-1 size-4 accent-current" checked={mode === 'cloud'} onChange={() => setMode('cloud')} />
          <span><strong>Facilitata</strong>: un abbonamento mensile, niente chiavi API né modelli da scegliere.</span>
        </label>
        <label className="flex items-start gap-2 text-body">
          <input type="radio" name="wizard-ai-mode" className="mt-1 size-4 accent-current" checked={mode === 'byok'} onChange={() => setMode('byok')} />
          <span><strong>Con la mia chiave</strong>: usi il tuo account OpenRouter o di un altro provider e scegli i modelli.</span>
        </label>
      </fieldset>
      {mode === 'cloud' && <CloudPanel onSynced={onCloud} />}
      {mode === 'byok' && byok}
    </div>
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
          <p className="text-body text-muted-foreground">Le fasi si salvano automaticamente quando scegli connessione e modello; Prova fa una chiamata minima prima di salvare.</p>
          <div className="rounded-lg border"><PhaseRows settings={settings} /></div>
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
      <div className="divide-y divide-border/60 rounded-lg border">
        <SettingsRow
          label="Connessione"
          htmlFor="wizard-connection"
          control={
            <Select id="wizard-connection" className="w-full @sm:w-60" value={connection} onChange={(e) => setConnection(e.target.value)}>
              {settings.connections.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </Select>
          }
        />
        <SettingsRow
          label="Modello"
          htmlFor="wizard-model"
          control={
            <div className="w-full @sm:w-60">
              <Input id="wizard-model" list="wizard-models" value={model} placeholder="es. deepseek/deepseek-v4-flash" onChange={(e) => setModel(e.target.value)} />
              <datalist id="wizard-models">
                {models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
          }
        />
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
