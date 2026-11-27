import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'

import { api, errorMessage, unwrap } from '@/api/client'
import {
  isTerminal,
  useAddModel,
  useAssignPhase,
  useClearPhase,
  useCreateConnection,
  useDeleteConnection,
  useJob,
  useRoute,
  useSaveRoute,
  useTestCredential,
  useTestModel,
  type RouteOut,
  type Settings,
} from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { Textarea } from '@/components/ui/textarea'
import { optionRevealClass, useOptionKey } from '@/lib/optionKey'
import { PROVIDERS, ROUTE_ROLES, defaultBaseUrl, providerLabel, type Provider } from '@/lib/settings'
import { SecretsSection, PricingSection } from './keys'
import {
  AutoSaveStatus,
  SaveFeedback,
  SettingsGroup,
  LabelWithInfo,
  SettingsRow,
  SettingsSelect as Select,
  SettingsSwitch,
} from './ui'
import { useAutoSave } from './useAutoSave'

type Connection = Settings['connections'][number]
type Phase = Settings['phases'][number]

// La sezione "Classificatore" (playground delle domande e mappatura) vive in jev-playground.tsx.
export { DecisionModelSection } from './jev-playground'

export function PromptEditorSection() {
  const client = useQueryClient()
  const prompts = useQuery({ queryKey: ['prompt-overrides'], queryFn: () => unwrap(api.GET('/api/v1/settings/prompts')) })
  const [phase, setPhase] = useState<'outline' | 'rewrite' | 'review' | 'image_description' | 'recall'>('outline')
  const [drafts, setDrafts] = useState<Partial<Record<typeof phase, string>>>({})
  const savedInstruction = prompts.data?.[phase]?.instruction ?? ''
  const instruction = drafts[phase] ?? savedInstruction

  const save = useMutation({
    mutationFn: (text: string) =>
      unwrap(api.PUT('/api/v1/settings/prompts/{phase}', { params: { path: { phase } }, body: { instruction: text } })),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['prompt-overrides'] }) },
  })

  const autoSave = useAutoSave(save, instruction, {
    delay: 600,
    enabled: !prompts.isPending,
    initial: savedInstruction,
  })

  return (
    <div className="flex flex-col gap-3">
      <p className="text-meta text-muted-foreground">
        Ciò che scrivi si aggiunge all'istruzione predefinita della fase, non la sostituisce: il predefinito, il contratto strutturato e la validazione di RT restano attivi. Svuota la casella per usare solo il predefinito.
      </p>
      <div className="divide-y divide-border/60 rounded-lg border bg-background">
        <SettingsRow
          label="Fase"
          htmlFor="prompt-phase"
          control={
            <Select
              id="prompt-phase"
              className="w-full @sm:w-60"
              value={phase}
              onChange={(e) => {
                autoSave.reset()
                setPhase(e.target.value as typeof phase)
              }}
            >
              <option value="outline">Scaletta</option>
              <option value="rewrite">Rielaborazione</option>
              <option value="review">Revisione</option>
              <option value="image_description">Descrizione immagini</option>
              <option value="recall">Recall</option>
            </Select>
          }
        />
        <SettingsRow
          label="Istruzioni aggiuntive"
          htmlFor="prompt-instruction"
          stacked
          status={autoSave}
          control={
            <Textarea
              id="prompt-instruction"
              className="font-mono text-meta"
              rows={12}
              maxLength={20000}
              placeholder={prompts.data?.[phase]?.default ?? ''}
              value={instruction}
              onChange={(e) => setDrafts((old) => ({ ...old, [phase]: e.target.value }))}
              onBlur={autoSave.flush}
            />
          }
        />
      </div>
    </div>
  )
}

const PHASE_HINTS: Record<string, string> = {
  outline: 'Organizza i segmenti temporali in una scaletta verificabile.',
  rewrite: 'Rielabora le unità conservando riferimenti e provenienza.',
  review: 'Cerca errori scientifici nel testo rielaborato.',
  recall: 'Genera domande per il ripasso attivo.',
  image_description: 'Descrive slide e immagini. Il modello selezionato deve supportare Vision.',
  enrichment_writer: 'Prepara idee e prompt JSON da una singola subunità, senza generare contenuti.',
  enrichment_visualizer: 'Genera HTML/SVG/JavaScript autonomo per grafici, matrici, diagrammi e simulazioni.',
  enrichment_image: 'Generatore di immagini tramite Images API. Usa un modello con output immagine su OpenRouter o OpenAI-compatible.',
  study_chat: 'Risponde alle domande nella chat dello Studio. Se non scelto, usa il modello della Revisione.',
}

// ------------------------------------------------------------------ modelli per fase

export function PhasesSection({ settings }: { settings: Settings }) {
  const estimate = useQuery({
    queryKey: ['settings-estimate'],
    queryFn: () => unwrap(api.GET('/api/v1/settings/estimate')),
  })

  return (
    <SettingsGroup
      id="fasi"
      title="Modelli per fase"
      description="Connessione e modello usati da ciascuna fase. Un modello nuovo viene aggiunto alla connessione. Prova fa una chiamata minima."
    >
      {estimate.data && (
        <div className="px-4 py-2.5 text-meta text-muted-foreground" data-testid="cost-estimate">
          Costo stimato con i modelli attuali:{' '}
          <strong className="font-semibold text-foreground">{estimate.data.formatted}</strong>
        </div>
      )}
      {settings.connections.length === 0 && (
        <div className="px-4 py-3">
          <Alert tone="warning">Crea prima una connessione qui sotto.</Alert>
        </div>
      )}
      <PhaseRows settings={settings} />
    </SettingsGroup>
  )
}

/** Le fasi, ognuna con connessione, modello, salvataggio automatico e Prova. Usate anche dalla configurazione guidata. */
const BATCH_INELIGIBLE_PHASES = new Set(['image_description', 'enrichment_image'])

export function PhaseRows({ settings }: { settings: Settings }) {
  return (
    <div className="@container divide-y divide-border/60">
      <div className="hidden bg-muted/30 px-4 py-2 text-meta font-medium text-muted-foreground @2xl:grid @2xl:grid-cols-[minmax(0,1fr)_14rem_14rem_5.5rem] @2xl:gap-x-3">
        <span>Fase</span>
        <span>Connessione</span>
        <span>Modello</span>
        <span className="sr-only">Prova</span>
      </div>
      {settings.phases.map((phase) => (
        <PhaseRow
          key={`${phase.job}:${phase.connection ?? ''}:${phase.model ?? ''}:${phase.batch ? 'batch' : 'sync'}`}
          phase={phase}
          connections={settings.connections}
        />
      ))}
    </div>
  )
}

function PhaseRow({ phase, connections }: { phase: Phase; connections: Connection[] }) {
  const assign = useAssignPhase()
  const clear = useClearPhase()
  const isStudyChat = phase.job === 'study_chat'
  const savedDisplay = phase.batch && phase.model && !phase.model.endsWith(':batch') ? `${phase.model}:batch` : (phase.model ?? '')
  const [connection, setConnection] = useState(phase.connection ?? '')
  const [model, setModel] = useState(savedDisplay)
  const selectedConn = connections.find((c) => c.name === connection)
  const models = selectedConn?.models ?? []
  const batchEligible = !isStudyChat && !BATCH_INELIGIBLE_PHASES.has(phase.job) && !!selectedConn?.supports_batch
  const batchModels = batchEligible ? (selectedConn?.batch_models ?? []) : []
  const trimmedModel = model.trim()
  const isBatchSelected = batchEligible && trimmedModel.endsWith(':batch')
  const listId = `modelli-${phase.job}`

  const autoSave = useAutoSave(
    assign,
    { connection, model: trimmedModel },
    {
      delay: 600,
      // Il nome del modello si salva all'uscita dal campo o con Invio: salvarlo a ogni pausa
      // registrava ogni prefisso digitato («re», «recraft/», …) tra i modelli della connessione.
      manual: true,
      enabled: Boolean(connection) && Boolean(trimmedModel),
      initial: { connection: phase.connection ?? '', model: savedDisplay },
      equals: (a, b) => a.connection === b.connection && a.model.trim() === b.model.trim(),
      serialize: ({ connection: conn, model: mod }) => {
        const clean = mod.trim()
        const batch = batchEligible && clean.endsWith(':batch')
        return {
          job: phase.job,
          connection: conn,
          model: batch ? clean.slice(0, -':batch'.length) : clean,
          batch,
        }
      },
    },
  )

  function handleConnectionChange(next: string) {
    setConnection(next)
    setModel('')
    autoSave.reset()
    if (isStudyChat && !next && phase.connection) {
      clear.mutate(phase.job)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (isStudyChat && !connection) {
      clear.mutate(phase.job)
      return
    }
    if (connection && trimmedModel) {
      autoSave.saveNow({ connection, model: trimmedModel })
    }
  }

  return (
    <form
      onSubmit={submit}
      className="px-4 py-3"
      data-testid="phase-row"
      data-job={phase.job}
      aria-label={`Fase ${phase.label}`}
    >
      <div className="grid grid-cols-1 items-center gap-x-3 gap-y-2 @2xl:grid-cols-[minmax(0,1fr)_14rem_14rem_5.5rem]">
        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="min-w-0">
            <span className="text-body font-medium text-foreground">
              <LabelWithInfo label={phase.label} info={PHASE_HINTS[phase.job]} infoLabel={phase.label} />
            </span>
          </div>
          {phase.model ? (
            <span className="min-w-0 break-words text-meta text-muted-foreground" data-testid="phase-saved">
              {phase.connection} · {phase.model}{phase.batch ? ' · batch' : ''}
            </span>
          ) : isStudyChat ? (
            <span className="text-meta text-muted-foreground" data-testid="phase-saved">
              Come la Revisione
            </span>
          ) : (
            <Badge tone="warning" className="w-fit">
              Non assegnato
            </Badge>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={`fase-${phase.job}-connessione`} className="text-meta text-muted-foreground @2xl:sr-only">Connessione</label>
          <Select
            id={`fase-${phase.job}-connessione`}
            aria-label="Connessione"
            className="w-full"
            value={connection}
            onChange={(e) => handleConnectionChange(e.target.value)}
          >
            <option value="">{isStudyChat ? 'Come la Revisione' : 'Scegli…'}</option>
            {connections.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={`fase-${phase.job}-modello`} className="text-meta text-muted-foreground @2xl:sr-only">Modello</label>
          <Input
            id={`fase-${phase.job}-modello`}
            className="h-9 w-full"
            list={listId}
            value={model}
            disabled={!connection}
            placeholder="es. openai/gpt-4.1"
            onChange={(e) => setModel(e.target.value)}
            onBlur={autoSave.flush}
          />
          <datalist id={listId}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
            {batchModels.map((bm) => {
              const value = bm.endsWith(':batch') ? bm : `${bm}:batch`
              return <option key={value} value={value} label={`${bm} · batch (−50%, risposte entro 24 h)`} />
            })}
          </datalist>
        </div>
        {!phase.job.startsWith('enrichment_') ? (
          <ModelTest
            connection={connection}
            model={trimmedModel.replace(/:batch$/, '')}
            label={phase.label}
            vision={phase.job === 'image_description'}
            className="contents"
            buttonClassName="w-full @2xl:w-full"
            resultClassName="@2xl:col-span-4"
          />
        ) : (
          <div className="hidden @2xl:block" aria-hidden="true" />
        )}
      </div>
      {autoSave.status !== 'idle' && (
        <div className="mt-1.5 flex justify-end">
          <AutoSaveStatus status={autoSave.status} error={autoSave.error} onRetry={autoSave.retry} />
        </div>
      )}
      {isBatchSelected && (
        <p className="mt-2 text-meta text-muted-foreground" data-testid="phase-batch-hint">
          Le risposte arrivano più tardi: RT deve poter lavorare in background (Impostazioni → Aspetto e lettura → Chiudendo la finestra con la X)
        </p>
      )}
      {clear.isError && (
        <Alert tone="danger" className="mt-2">
          {errorMessage(clear.error)}
        </Alert>
      )}
    </form>
  )
}

// ------------------------------------------------------------------ prova di un modello

/** Pulsante "Prova": chiamata minima a connessione e modello scritti nel form (anche non
 * salvati) con esito, latenza ed eventuale errore del provider. L'esito resta finché non si
 * cambia connessione o modello. */
export function ModelTest({
  connection,
  model,
  label,
  vision = false,
  className,
  buttonClassName,
  resultClassName,
}: {
  connection: string
  model: string
  label?: string
  vision?: boolean
  className?: string
  buttonClassName?: string
  resultClassName?: string
}) {
  const test = useTestModel()
  const tested = test.variables
  const current = !!tested && tested.connection === connection && tested.model === model.trim() && !!tested.vision === vision
  let outcome = null
  if (current && test.isPending) {
    outcome = (
      <p role="status" className="text-meta text-muted-foreground">
        Prova in corso…
      </p>
    )
  } else if (current && test.isError) {
    outcome = <Alert tone="danger">{errorMessage(test.error)}</Alert>
  } else if (current && test.data) {
    const r = test.data
    const latency = r.latency_ms != null ? `${r.latency_ms} ms` : null
    outcome = r.ok ? (
      <p role="status" className="text-meta text-success" data-testid="model-test-result">
        Raggiungibile{latency ? ` · ${latency}` : ''} · {r.message}
      </p>
    ) : (
      <Alert tone="danger" data-testid="model-test-result">
        Non raggiungibile{latency ? ` (${latency})` : ''}: {r.message}
      </Alert>
    )
  }
  return (
    <div className={className}>
      <Button
        type="button"
        variant="outline"
        className={buttonClassName}
        aria-label={label ? `Prova il modello di ${label}` : 'Prova il modello'}
        disabled={!connection || !model.trim() || (current && test.isPending)}
        onClick={() => test.mutate({ connection, model: model.trim(), vision })}
      >
        Prova
      </Button>
      {outcome && (
        <div className={resultClassName}>{outcome}</div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ connessioni

export function ConnectionsSection({ settings }: { settings: Settings }) {
  return (
    <SettingsGroup
      id="connessioni"
      title="Connessioni"
      description="Provider LLM con le loro chiavi. Con più chiavi RT le alterna automaticamente."
    >
      {settings.connections.length === 0 && (
        <p className="px-4 py-3 text-body text-muted-foreground">Nessuna connessione.</p>
      )}
      {settings.connections.map((c) => (
        <ConnectionItem key={c.name} connection={c} settings={settings} />
      ))}
      {Object.keys(settings.pricing ?? {}).filter(provider => !settings.connections.some(c => c.provider === provider)).map(provider => (
        <div key={provider} className="flex flex-col gap-3 px-4 py-4">
          <h3 className="text-body font-medium">{providerLabel(provider)} · senza connessione</h3>
          <PricingSection settings={settings} connection={{ name: `costi-${provider}`, provider, base_url: '', credentials: [], models: Object.keys(settings.pricing[provider]), supports_batch: false }} />
        </div>
      ))}
    </SettingsGroup>
  )
}

function ConnectionItem({ connection, settings }: { connection: Connection; settings: Settings }) {
  const addModel = useAddModel()
  const [model, setModel] = useState('')
  const optionDown = useOptionKey()
  const deletion = useDeleteConnection()
  const [confirm, setConfirm] = useState(false)
  const keys = connection.credentials.filter((c) => c.set).length
  return (
    <div className="group relative flex flex-col gap-4 px-4 py-4" data-testid="connection" data-name={connection.name} aria-label={`Connessione ${connection.name}`} role="group">
      <Button type="button" variant="ghost" size="icon" aria-label={`Elimina la connessione ${connection.name}`}
        className={`${optionRevealClass(optionDown)} absolute right-3 top-3 text-danger`}
        onClick={() => { deletion.reset(); setConfirm(true) }}><Trash2 /></Button>
      <ConfirmDialog open={confirm} title="Elimina connessione" confirmLabel="Elimina"
        confirmDisabled={deletion.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => deletion.mutate(connection.name, { onSuccess: () => setConfirm(false) })}>
        <p>
          Eliminare la connessione «{connection.name}» con i suoi modelli
          {keys > 0 ? ` e ${keys === 1 ? 'la sua chiave' : `le sue ${keys} chiavi`} (dall'archivio di RT e da .env)` : ''}?
        </p>
        <p className="mt-2 text-meta text-muted-foreground">Le fasi e le route che la usano vanno prima assegnate a un'altra connessione.</p>
        {deletion.isError && <Alert tone="danger" className="mt-3">{errorMessage(deletion.error)}</Alert>}
      </ConfirmDialog>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pr-10">
        <h3 className="text-body font-medium text-foreground">{connection.name}</h3>
        <span className="text-meta text-muted-foreground">
          {providerLabel(connection.provider)} · {connection.base_url}
        </span>
      </div>
      <SecretsSection settings={settings} connection={connection} />
      <PricingSection settings={settings} connection={connection} />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5" data-testid="connection-models">
          {connection.models.length === 0 && <span className="text-meta text-muted-foreground">Nessun modello.</span>}
          {connection.models.map((m) => (
            <Badge key={m}>{m}</Badge>
          ))}
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            addModel.mutate({ connection: connection.name, model: model.trim() }, { onSuccess: () => setModel('') })
          }}
        >
          <Input aria-label={`Nuovo modello per ${connection.name}`} value={model} placeholder="Aggiungi un modello" onChange={(e) => setModel(e.target.value)} />
          <Button type="submit" variant="outline" disabled={!model.trim() || addModel.isPending}>
            <Plus /> Aggiungi
          </Button>
        </form>
        {addModel.isError && <Alert tone="danger">{errorMessage(addModel.error)}</Alert>}
      </div>
    </div>
  )
}

/** Nuova connessione: nome, provider, base URL, una o più chiavi (solo in scrittura). */
export function NewConnectionForm({ onCreated, submitLabel = 'Crea connessione' }: { onCreated?: (name: string) => void; submitLabel?: string }) {
  const create = useCreateConnection()
  const [name, setName] = useState('')
  const [provider, setProvider] = useState<Provider>('openrouter')
  const [baseUrl, setBaseUrl] = useState(defaultBaseUrl('openrouter'))
  const [keys, setKeys] = useState([''])

  function submit(e: FormEvent) {
    e.preventDefault()
    const body = { name: name.trim(), provider, base_url: baseUrl.trim(), api_keys: keys.map((k) => k.trim()).filter(Boolean) }
    create.mutate(body, {
      onSuccess: () => {
        setName('')
        setKeys([''])
        onCreated?.(body.name)
      },
    })
  }

  return (
    <form className="divide-y divide-border/60" onSubmit={submit} aria-label="Nuova connessione">
      <SettingsRow
        label="Nome connessione"
        htmlFor="conn-name"
        control={<Input id="conn-name" className="w-full @sm:w-60" value={name} onChange={(e) => setName(e.target.value)} placeholder="es. OpenRouter personale" required />}
      />
      <SettingsRow
        label="Provider"
        htmlFor="conn-provider"
        control={
          <Select
            id="conn-provider"
            className="w-full @sm:w-60"
            value={provider}
            onChange={(e) => {
              const next = e.target.value as Provider
              if (!baseUrl.trim() || baseUrl === defaultBaseUrl(provider)) setBaseUrl(defaultBaseUrl(next))
              setProvider(next)
            }}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
        }
      />
      <SettingsRow
        label="Base URL"
        htmlFor="conn-base-url"
        control={<Input id="conn-base-url" className="w-full @sm:w-60" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />}
      />
      {keys.map((key, i) => (
        <SettingsRow
          key={i}
          label={`Chiave API ${i + 1}`}
          htmlFor={`conn-key-${i}`}
          control={
            <div className="w-full @sm:w-60">
              <SecretInput
                id={`conn-key-${i}`}
                value={key}
                required={i === 0}
                onChange={(e) => setKeys((c) => c.map((k, j) => (j === i ? e.target.value : k)))}
              />
            </div>
          }
        />
      ))}
      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => setKeys((c) => [...c, ''])}>
            <Plus /> Aggiungi chiave
          </Button>
          <Button type="submit" disabled={create.isPending || !name.trim() || !keys[0].trim()}>
            {submitLabel}
          </Button>
        </div>
        <p className="text-meta text-muted-foreground">Le chiavi vanno nell'archivio dei segreti di RT e non si rileggono più dalla pagina.</p>
        <SaveFeedback mutation={create} success="Connessione creata." />
      </div>
    </form>
  )
}

export function NewConnectionSection() {
  return (
    <SettingsGroup id="nuova-connessione" title="Nuova connessione">
      <NewConnectionForm />
    </SettingsGroup>
  )
}

// ------------------------------------------------------------------ route avanzate

export function RoutesSection({ settings }: { settings: Settings }) {
  const [params, setParams] = useSearchParams()
  const job = params.get('fase') ?? settings.phases[0]?.job ?? 'outline'
  const role = params.get('ruolo') ?? 'primary'
  const route = useRoute(job, role)
  const save = useSaveRoute()

  function set(key: string, value: string) {
    save.reset()
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true })
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-meta text-muted-foreground">
        Il primario è lo stesso dei modelli per fase. Il secondario si usa quando il primario fallisce (dopo aver provato tutte le chiavi in rotazione).
      </p>
      <div className="divide-y divide-border/60 rounded-lg border bg-background">
        <SettingsRow
          label="Fase"
          htmlFor="route-job"
          control={
            <Select id="route-job" className="w-full @sm:w-60" value={job} onChange={(e) => set('fase', e.target.value)}>
              {settings.phases.map((p) => (
                <option key={p.job} value={p.job}>
                  {p.label}
                </option>
              ))}
            </Select>
          }
        />
        <SettingsRow
          label="Ruolo"
          htmlFor="route-role"
          control={
            <Select id="route-role" className="w-full @sm:w-60" value={role} onChange={(e) => set('ruolo', e.target.value)}>
              {ROUTE_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
          }
        />
        {route.isPending && <p className="px-4 py-3 text-body text-muted-foreground">Carico la route…</p>}
        {route.isError && <div className="px-4 py-3"><Alert tone="danger">{errorMessage(route.error)}</Alert></div>}
        {route.data && <RouteForm key={JSON.stringify(route.data)} route={route.data} settings={settings} save={save} />}
      </div>
    </div>
  )
}

function RouteForm({ route, settings, save }: { route: RouteOut; settings: Settings; save: ReturnType<typeof useSaveRoute> }) {
  const [provider, setProvider] = useState(route.provider)
  const [credential, setCredential] = useState(route.credential)
  const [model, setModel] = useState(route.model)
  const [baseUrl, setBaseUrl] = useState(route.base_url)
  const [roundRobin, setRoundRobin] = useState(route.round_robin)
  const credentials = settings.credentials.filter((c) => c.provider === provider)

  const state = { provider, credential, model, baseUrl, roundRobin }
  const valid = Boolean(model.trim()) && (Boolean(credential) || (route.role === 'primary' && roundRobin))

  const autoSave = useAutoSave(save, state, {
    delay: 600,
    enabled: valid,
    initial: {
      provider: route.provider,
      credential: route.credential,
      model: route.model,
      baseUrl: route.base_url,
      roundRobin: route.round_robin,
    },
    serialize: (val) => ({
      job: route.job,
      role: route.role,
      body: {
        provider: val.provider,
        credential: val.credential,
        model: val.model.trim(),
        base_url: val.baseUrl.trim(),
        round_robin: route.role === 'primary' && val.roundRobin,
        batch: false,
      },
    }),
  })

  return (
    <div className="divide-y divide-border/60" aria-label="Route">
      <SettingsRow
        label="Provider della route"
        htmlFor="route-provider"
        control={
          <Select
            id="route-provider"
            className="w-full @sm:w-60"
            value={provider}
            onChange={(e) => {
              const nextProv = e.target.value
              const nextUrl = !baseUrl.trim() || baseUrl === defaultBaseUrl(provider) ? defaultBaseUrl(nextProv) : baseUrl
              setBaseUrl(nextUrl)
              setProvider(nextProv)
              setCredential('')
            }}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
        }
      />
      <SettingsRow
        label="Chiave"
        htmlFor="route-credential"
        control={
          <Select
            id="route-credential"
            className="w-full @sm:w-60"
            value={credential}
            onChange={(e) => {
              const nextCred = e.target.value
              setCredential(nextCred)
              if (model.trim() && (nextCred || (route.role === 'primary' && roundRobin))) {
                autoSave.saveNow({ provider, credential: nextCred, model, baseUrl, roundRobin })
              }
            }}
          >
            <option value="">Scegli…</option>
            {credentials.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
                {c.set ? '' : ' (mancante)'}
              </option>
            ))}
          </Select>
        }
      />
      <SettingsRow
        label="Modello della route"
        htmlFor="route-model"
        status={autoSave}
        control={
          <Input
            id="route-model"
            className="w-full @sm:w-60"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            onBlur={autoSave.flush}
            placeholder="es. deepseek/deepseek-v4-flash"
          />
        }
      />
      <SettingsRow
        label="Base URL della route"
        htmlFor="route-base-url"
        control={
          <Input
            id="route-base-url"
            className="w-full @sm:w-60"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            onBlur={autoSave.flush}
          />
        }
      />
      {route.role === 'primary' && (
        <SettingsSwitch
          id="route-rr"
          label="Alterna tutte le chiavi del provider"
          checked={roundRobin}
          onChange={(next) => {
            setRoundRobin(next)
            if (model.trim() && (credential || next)) {
              autoSave.saveNow({ provider, credential, model, baseUrl, roundRobin: next })
            }
          }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ prova di una chiave

/** Pulsante "Prova": accoda il job credential_test e ne mostra l'esito (mai la chiave).
 * `action` prende il posto di Prova (Chiavi: "Elimina" mentre è premuto Option). */
export function CredentialTest({ credential, settings, action }: { credential: string; settings: Settings; action?: ReactNode }) {
  const connection = settings.connections.find((c) => c.credentials.some((k) => k.name === credential))
  const provider = settings.credentials.find((c) => c.name === credential)?.provider ?? connection?.provider
  const assigned = settings.phases.find((p) => p.connection === connection?.name)?.model
  const [model, setModel] = useState(assigned ?? connection?.models[0] ?? '')
  const test = useTestCredential()
  const job = useJob(test.data?.job_id)
  const listId = `modelli-prova-${credential}`

  const state = job.data?.state
  const result = job.data?.result as { ok?: boolean; message?: string } | null | undefined
  let outcome = null
  if (test.isError) outcome = <Alert tone="danger">{errorMessage(test.error)}</Alert>
  else if (test.data && !isTerminal(state)) {
    outcome = (
      <p role="status" className="text-meta text-muted-foreground">
        {test.data.worker_available ? 'Prova in corso…' : 'Nessun worker attivo: la prova resta in coda finché RT non viene riavviato con la web.'}
      </p>
    )
  } else if (state === 'succeeded' && result) {
    outcome = result.ok ? (
      <p role="status" className="text-meta text-success" data-testid="credential-test-result">
        Riuscita: {result.message}
      </p>
    ) : (
      <Alert tone="danger" data-testid="credential-test-result">
        Non riuscita: {result.message}
      </Alert>
    )
  } else if (state === 'failed' || state === 'cancelled') {
    outcome = <Alert tone="danger">Prova non eseguita: {job.data?.error ?? state}</Alert>
  }

  return (
    <div className="flex flex-col gap-2">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          test.mutate({ credential, model: model.trim(), provider: provider ?? null, base_url: connection?.base_url || null, mock: false })
        }}
      >
        <div className="flex min-w-48 flex-1 flex-col gap-1">
          <Input aria-label={`Modello per provare ${credential}`} list={listId} value={model} placeholder="Modello per la prova" onChange={(e) => setModel(e.target.value)} />
          <datalist id={listId}>
            {(connection?.models ?? []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
        {action ?? (
          <Button type="submit" variant="outline" disabled={!model.trim() || test.isPending || (!!test.data && !isTerminal(state))}>
            Prova
          </Button>
        )}
      </form>
      {outcome}
    </div>
  )
}
