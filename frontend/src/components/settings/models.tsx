import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'

import { api, errorMessage, unwrap } from '@/api/client'
import {
  isTerminal,
  useAddModel,
  useAssignPhase,
  useCreateConnection,
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
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { Select } from '@/components/ui/select'
import { PROVIDERS, ROUTE_ROLES, defaultBaseUrl, providerLabel, type Provider } from '@/lib/settings'
import { Checkbox, Field, SaveFeedback, SecretBadge, Section } from './common'

type Connection = Settings['connections'][number]
type Phase = Settings['phases'][number]

export function DecisionModelSection() {
  const client = useQueryClient()
  const configured = useQuery({ queryKey: ['decision-model'], queryFn: () => unwrap(api.GET('/api/v1/settings/decision-model')) })
  const [modelDraft, setModel] = useState<string | null>(null)
  const [relevanceModelDraft, setRelevanceModel] = useState<string | null>(null)
  const [credentialDraft, setCredential] = useState<string | null>(null)
  const [thresholdDraft, setThreshold] = useState<number | null>(null)
  const [shadowDraft, setShadow] = useState<boolean | null>(null)
  const [enabledDraft, setEnabled] = useState<boolean | null>(null)
  const [relevanceModeDraft, setRelevanceMode] = useState<'disabled' | 'shadow' | 'active' | null>(null)
  const [relevancePromptDraft, setRelevancePrompt] = useState<string | null>(null)
  const [relevanceThresholdDraft, setRelevanceThreshold] = useState<number | null>(null)
  const model = modelDraft ?? configured.data?.model ?? ''
  const relevanceModel = relevanceModelDraft ?? configured.data?.relevance_model ?? ''
  const credential = credentialDraft ?? configured.data?.credential ?? 'openrouter'
  const threshold = thresholdDraft ?? configured.data?.threshold ?? 0.85
  const shadow = shadowDraft ?? configured.data?.shadow ?? true
  const enabled = enabledDraft ?? configured.data?.enabled ?? false
  const relevanceMode = relevanceModeDraft ?? configured.data?.relevance_mode ?? 'shadow'
  const relevancePrompt = relevancePromptDraft ?? configured.data?.relevance_prompt ?? ''
  const relevanceThreshold = relevanceThresholdDraft ?? configured.data?.relevance_threshold ?? 0.85
  const probe = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/decision-model/probe', {
    body: { model: relevanceModel, relevance_model: relevanceModel, credential, threshold, enabled: true, shadow, relevance_mode: relevanceMode, relevance_prompt: relevancePrompt, relevance_threshold: relevanceThreshold },
  })) })
  const probePrefilter = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/settings/decision-model/probe', {
    body: { model, relevance_model: relevanceModel, credential, threshold, enabled: true, shadow, relevance_mode: relevanceMode, relevance_prompt: relevancePrompt, relevance_threshold: relevanceThreshold },
  })) })
  const save = useMutation({ mutationFn: () => unwrap(api.PUT('/api/v1/settings/decision-model', {
    body: { model, relevance_model: relevanceModel, credential, threshold, enabled, shadow, relevance_mode: relevanceMode, relevance_prompt: relevancePrompt, relevance_threshold: relevanceThreshold },
  })), onSuccess: () => { void client.invalidateQueries({ queryKey: ['decision-model'] }) } })
  return <Section id="classificatore" title="Decisioni JEV"
    description="Il gate di rilevanza decide quali unità inviare a review e Recall. Il prefiltro errori è un controllo separato prima della review canonica.">
    <Field label="Modello JEV rilevanza" htmlFor="relevance-model-name"><Input id="relevance-model-name" value={relevanceModel} onChange={(e) => setRelevanceModel(e.target.value)} placeholder="Facoltativo: ID del modello Jev choice" /></Field>
    <Field label="Credenziale" htmlFor="decision-model-credential"><Input id="decision-model-credential" value={credential} onChange={(e) => setCredential(e.target.value)} /></Field>
    <Field label="Comportamento JEV" htmlFor="relevance-mode"><Select id="relevance-mode" value={relevanceMode} onChange={(e) => setRelevanceMode(e.target.value as typeof relevanceMode)}>
      <option value="disabled">Disattivato · tutte le unità passano, nessuna chiamata</option>
      <option value="shadow">Ombra · classifica, tutte le unità passano</option>
      <option value="active">Filtro attivo · solo unità didattiche a review e Recall</option>
    </Select></Field>
    <Field label="Soglia di confidenza rilevanza" htmlFor="relevance-threshold"><Input id="relevance-threshold" type="number" min="0" max="1" step="0.01" value={relevanceThreshold} onChange={(e) => setRelevanceThreshold(Number(e.target.value))} /></Field>
    <Field label="Istruzioni aggiuntive per la rilevanza" htmlFor="relevance-prompt"><textarea id="relevance-prompt" className="w-full rounded border bg-background p-2 text-sm" rows={4} value={relevancePrompt} onChange={(e) => setRelevancePrompt(e.target.value)} /></Field>
    <p className="text-xs text-muted-foreground">Il gate usa Jev choice con tre classi. Un modello vuoto o un errore lasciano passare tutte le unità. Verifica un campione in Ombra prima di attivare il filtro.</p>
    <div className="border-t pt-3"><h3 className="font-medium">Prefiltro errori (prima della review)</h3>
      <Field label="Modello del prefiltro errori" htmlFor="decision-model-name"><Input id="decision-model-name" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Facoltativo: ID del modello Jev" /></Field>
      <Field label="Soglia di confidenza del prefiltro" htmlFor="decision-model-threshold"><Input id="decision-model-threshold" type="number" min="0" max="1" step="0.01" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} /></Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Abilita il prefiltro errori</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shadow} onChange={(e) => setShadow(e.target.checked)} />Prefiltro in ombra (non salta la review)</label>
    </div>
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!relevanceModel.trim() || probe.isPending} onClick={() => probe.mutate()}>Prova JEV rilevanza</Button>
      <Button variant="outline" disabled={!model.trim() || probePrefilter.isPending} onClick={() => probePrefilter.mutate()}>Prova prefiltro</Button>
      <Button disabled={save.isPending || (enabled && !model.trim())} onClick={() => save.mutate()}>Salva</Button></div>
    {probe.isSuccess && <p role="status" className="text-xs text-success">Protocollo verificato · confidenza {probe.data.confidence}</p>}
    {probe.isError && <Alert tone="danger">{errorMessage(probe.error)}</Alert>}
    {probePrefilter.isError && <Alert tone="danger">{errorMessage(probePrefilter.error)}</Alert>}
    {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
  </Section>
}

export function PromptEditorSection() {
  const client = useQueryClient()
  const prompts = useQuery({ queryKey: ['prompt-overrides'], queryFn: () => unwrap(api.GET('/api/v1/settings/prompts')) })
  const [phase, setPhase] = useState<'outline' | 'rewrite' | 'review' | 'image_description' | 'recall'>('outline')
  const [drafts, setDrafts] = useState<Partial<Record<typeof phase, string>>>({})
  const instruction = drafts[phase] ?? prompts.data?.[phase]?.instruction ?? ''
  const save = useMutation({ mutationFn: () => unwrap(api.PUT('/api/v1/settings/prompts/{phase}', {
    params: { path: { phase } }, body: { instruction },
  })), onSuccess: () => { void client.invalidateQueries({ queryKey: ['prompt-overrides'] }) } })
  return <Section id="prompt" title="Istruzioni dei prompt"
    description="Aggiungi istruzioni alle fasi; il contratto strutturato e la validazione di RT restano attivi. Salva un campo vuoto per ripristinare il predefinito.">
    <Field label="Fase" htmlFor="prompt-phase"><Select id="prompt-phase" value={phase} onChange={(e) => setPhase(e.target.value as typeof phase)}>
      <option value="outline">Scaletta</option><option value="rewrite">Rielaborazione</option><option value="review">Revisione</option>
      <option value="image_description">Descrizione immagini</option><option value="recall">Recall</option>
    </Select></Field>
    <details className="text-xs"><summary className="cursor-pointer">Mostra istruzione predefinita</summary>
      <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded border p-2">{prompts.data?.[phase]?.default}</pre></details>
    <Field label="Istruzioni personalizzate" htmlFor="prompt-instruction"><textarea id="prompt-instruction"
      className="w-full rounded border bg-background p-2 text-sm" rows={6} maxLength={20000}
      value={instruction} onFocus={(e) => e.currentTarget.select()} onChange={(e) => setDrafts((old) => ({ ...old, [phase]: e.target.value }))} /></Field>
    <Button disabled={save.isPending || prompts.isPending} onClick={() => save.mutate()}>Salva istruzioni</Button>
    {save.isSuccess && <p role="status" className="text-xs text-success">Istruzioni salvate.</p>}
    {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
  </Section>
}

const PHASE_HINTS: Record<string, string> = {
  outline: 'Organizza i segmenti temporali in una scaletta verificabile.',
  rewrite: 'Rielabora le unità conservando riferimenti e provenienza.',
  review: 'Cerca errori scientifici nel testo rielaborato.',
  recall: 'Genera domande per il ripasso attivo.',
  image_description: 'Descrive slide e immagini: richiede visione.',
  image_unit_judge: 'Associa le immagini alle unità della lezione.',
}

// ------------------------------------------------------------------ modelli per fase

export function PhasesSection({ settings }: { settings: Settings }) {
  return (
    <Section
      id="fasi"
      title="Modelli per fase"
      description="Connessione e modello usati da ciascuna delle sei fasi. Un modello nuovo viene aggiunto alla connessione. Prova fa una chiamata minima, anche prima di salvare."
    >
      {settings.connections.length === 0 && <Alert tone="warning">Crea prima una connessione qui sotto.</Alert>}
      <PhaseRows settings={settings} />
    </Section>
  )
}

/** Le sei fasi, ognuna con connessione, modello, Salva e Prova. Usate anche dalla configurazione
 * guidata ("Scegli per ogni fase"). */
export function PhaseRows({ settings }: { settings: Settings }) {
  return (
    <div className="flex flex-col divide-y">
      {settings.phases.map((phase) => (
        <PhaseRow key={`${phase.job}:${phase.connection ?? ''}:${phase.model ?? ''}`} phase={phase} connections={settings.connections} />
      ))}
    </div>
  )
}

function PhaseRow({ phase, connections }: { phase: Phase; connections: Connection[] }) {
  const assign = useAssignPhase()
  const [connection, setConnection] = useState(phase.connection ?? '')
  const [model, setModel] = useState(phase.model ?? '')
  const models = connections.find((c) => c.name === connection)?.models ?? []
  const dirty = connection !== (phase.connection ?? '') || model !== (phase.model ?? '')
  const listId = `modelli-${phase.job}`
  function submit(e: FormEvent) {
    e.preventDefault()
    assign.mutate({ job: phase.job, connection, model: model.trim() })
  }
  return (
    <form
      onSubmit={submit}
      className="grid grid-cols-1 items-end gap-2 py-3 first:pt-0 sm:grid-cols-[10rem_1fr_1fr_auto_auto]"
      data-testid="phase-row"
      data-job={phase.job}
      aria-label={`Fase ${phase.label}`}
    >
      <div className="flex flex-col gap-1 self-center">
        <span className="text-sm font-semibold" title={PHASE_HINTS[phase.job]} tabIndex={0} aria-label={`${phase.label}: ${PHASE_HINTS[phase.job]}`}>{phase.label}</span>
        {phase.job === 'image_description' && <span className="text-[11px] text-muted-foreground">Richiede visione</span>}
        {phase.model ? (
          <span className="text-[11px] text-muted-foreground" data-testid="phase-saved">
            {phase.connection} · {phase.model}
          </span>
        ) : (
          <Badge tone="warning" className="w-fit">
            Non assegnato
          </Badge>
        )}
      </div>
      <Field label="Connessione" htmlFor={`fase-${phase.job}-connessione`}>
        <Select
          id={`fase-${phase.job}-connessione`}
          value={connection}
          onChange={(e) => {
            setConnection(e.target.value)
            setModel('')
          }}
        >
          <option value="">Scegli…</option>
          {connections.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Modello" htmlFor={`fase-${phase.job}-modello`}>
        <Input
          id={`fase-${phase.job}-modello`}
          list={listId}
          value={model}
          disabled={!connection}
          placeholder="es. openai/gpt-4.1"
          onChange={(e) => setModel(e.target.value)}
        />
        <datalist id={listId}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </Field>
      <Button type="submit" variant={dirty ? 'default' : 'outline'} disabled={!connection || !model.trim() || assign.isPending || !dirty}>
        Salva
      </Button>
      <ModelTest connection={connection} model={model} label={phase.label} vision={phase.job === 'image_description'} className="contents" resultClassName="sm:col-span-5" />
      {assign.isError && (
        <Alert tone="danger" className="sm:col-span-5">
          {errorMessage(assign.error)}
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
  resultClassName,
}: {
  connection: string
  model: string
  label?: string
  vision?: boolean
  className?: string
  resultClassName?: string
}) {
  const test = useTestModel()
  const tested = test.variables
  const current = !!tested && tested.connection === connection && tested.model === model.trim() && !!tested.vision === vision
  let outcome = null
  if (current && test.isPending) {
    outcome = (
      <p role="status" className="text-xs text-muted-foreground">
        Prova in corso…
      </p>
    )
  } else if (current && test.isError) {
    outcome = <Alert tone="danger">{errorMessage(test.error)}</Alert>
  } else if (current && test.data) {
    const r = test.data
    const latency = r.latency_ms != null ? `${r.latency_ms} ms` : null
    outcome = r.ok ? (
      <p role="status" className="text-xs text-success" data-testid="model-test-result">
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
        variant="outline"
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
    <Section id="connessioni" title="Connessioni" description="Provider LLM con le loro chiavi. Con più chiavi RT le alterna automaticamente.">
      {settings.connections.length === 0 && <p className="text-sm text-muted-foreground">Nessuna connessione.</p>}
      {settings.connections.map((c) => (
        <ConnectionItem key={c.name} connection={c} />
      ))}
    </Section>
  )
}

function ConnectionItem({ connection }: { connection: Connection }) {
  const addModel = useAddModel()
  const [model, setModel] = useState('')
  return (
    <div className="rounded-lg border p-4" data-testid="connection" data-name={connection.name} aria-label={`Connessione ${connection.name}`} role="group">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-bold">{connection.name}</h3>
        <span className="text-xs text-muted-foreground">
          {providerLabel(connection.provider)} · {connection.base_url}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Chiavi">
        {connection.credentials.map((cred) => (
          <span key={cred.name} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            {cred.name} <SecretBadge set={cred.set} />
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5" data-testid="connection-models">
        {connection.models.length === 0 && <span className="text-xs text-muted-foreground">Nessun modello.</span>}
        {connection.models.map((m) => (
          <Badge key={m}>{m}</Badge>
        ))}
      </div>
      <form
        className="mt-3 flex gap-2"
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
      {addModel.isError && <Alert tone="danger" className="mt-2">{errorMessage(addModel.error)}</Alert>}
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
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label="Nuova connessione">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Nome connessione" htmlFor="conn-name">
          <Input id="conn-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="es. OpenRouter personale" required />
        </Field>
        <Field label="Provider" htmlFor="conn-provider">
          <Select
            id="conn-provider"
            value={provider}
            onChange={(e) => {
              const next = e.target.value as Provider
              // Il base URL segue il provider finché è quello predefinito.
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
        </Field>
        <Field label="Base URL" htmlFor="conn-base-url">
          <Input id="conn-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
        </Field>
      </div>
      <div className="flex flex-col gap-2">
        {keys.map((key, i) => (
          <Field key={i} label={`Chiave API ${i + 1}`} htmlFor={`conn-key-${i}`}>
            <SecretInput
              id={`conn-key-${i}`}
              value={key}
              required={i === 0}
              onChange={(e) => setKeys((c) => c.map((k, j) => (j === i ? e.target.value : k)))}
            />
          </Field>
        ))}
        <div>
          <Button variant="outline" size="sm" onClick={() => setKeys((c) => [...c, ''])}>
            <Plus /> Aggiungi chiave
          </Button>
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">Le chiavi vanno nell'archivio dei segreti di RT e non si rileggono più dalla pagina.</p>
      <div>
        <Button type="submit" disabled={create.isPending || !name.trim() || !keys[0].trim()}>
          {submitLabel}
        </Button>
      </div>
      <SaveFeedback mutation={create} success="Connessione creata." />
    </form>
  )
}

export function NewConnectionSection() {
  return (
    <Section id="nuova-connessione" title="Nuova connessione">
      <NewConnectionForm />
    </Section>
  )
}

// ------------------------------------------------------------------ route avanzate

export function RoutesSection({ settings }: { settings: Settings }) {
  const [params, setParams] = useSearchParams()
  const job = params.get('fase') ?? settings.phases[0]?.job ?? 'outline'
  const role = params.get('ruolo') ?? 'primary'
  const route = useRoute(job, role)
  // La mutation sta qui: dopo il salvataggio la route riletta rimonta il form (key).
  const save = useSaveRoute()

  function set(key: string, value: string) {
    save.reset()
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true })
  }

  return (
    <Section
      id="route"
      title="Route avanzate"
      description="Modello primario, secondario e di ripiego per ogni errore. Il primario è lo stesso dei modelli per fase."
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Fase" htmlFor="route-job">
          <Select id="route-job" value={job} onChange={(e) => set('fase', e.target.value)}>
            {settings.phases.map((p) => (
              <option key={p.job} value={p.job}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Ruolo" htmlFor="route-role">
          <Select id="route-role" value={role} onChange={(e) => set('ruolo', e.target.value)}>
            {ROUTE_ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {route.isPending && <p className="text-sm text-muted-foreground">Carico la route…</p>}
      {route.isError && <Alert tone="danger">{errorMessage(route.error)}</Alert>}
      {route.data && <RouteForm key={JSON.stringify(route.data)} route={route.data} settings={settings} save={save} />}
      <SaveFeedback mutation={save} />
    </Section>
  )
}

function RouteForm({ route, settings, save }: { route: RouteOut; settings: Settings; save: ReturnType<typeof useSaveRoute> }) {
  const [provider, setProvider] = useState(route.provider)
  const [credential, setCredential] = useState(route.credential)
  const [model, setModel] = useState(route.model)
  const [baseUrl, setBaseUrl] = useState(route.base_url)
  const [roundRobin, setRoundRobin] = useState(route.round_robin)
  const credentials = settings.credentials.filter((c) => c.provider === provider)

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate({
      job: route.job,
      role: route.role,
      body: { provider, credential, model: model.trim(), base_url: baseUrl.trim(), round_robin: route.role === 'primary' && roundRobin },
    })
  }

  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={submit} aria-label="Route">
      <Field label="Provider della route" htmlFor="route-provider">
        <Select
          id="route-provider"
          value={provider}
          onChange={(e) => {
            if (!baseUrl.trim() || baseUrl === defaultBaseUrl(provider)) setBaseUrl(defaultBaseUrl(e.target.value))
            setProvider(e.target.value)
            setCredential('')
          }}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Chiave" htmlFor="route-credential">
        <Select id="route-credential" value={credential} onChange={(e) => setCredential(e.target.value)}>
          <option value="">Scegli…</option>
          {credentials.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
              {c.set ? '' : ' (mancante)'}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Modello della route" htmlFor="route-model">
        <Input id="route-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="es. deepseek/deepseek-v4-flash" />
      </Field>
      <Field label="Base URL della route" htmlFor="route-base-url">
        <Input id="route-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </Field>
      {route.role === 'primary' && (
        <div className="sm:col-span-2">
          <Checkbox id="route-rr" label="Alterna tutte le chiavi del provider" checked={roundRobin} onChange={setRoundRobin} />
        </div>
      )}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={save.isPending || !model.trim() || (!credential && !roundRobin)}>
          Salva route
        </Button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ prova di una chiave

/** Pulsante "Prova": accoda il job credential_test e ne mostra l'esito (mai la chiave). */
export function CredentialTest({ credential, settings }: { credential: string; settings: Settings }) {
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
      <p role="status" className="text-xs text-muted-foreground">
        {test.data.worker_available ? 'Prova in corso…' : 'Nessun worker attivo: la prova resta in coda finché RT non viene riavviato con la web.'}
      </p>
    )
  } else if (state === 'succeeded' && result) {
    outcome = result.ok ? (
      <p role="status" className="text-xs text-success" data-testid="credential-test-result">
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
        <Button type="submit" variant="outline" disabled={!model.trim() || test.isPending || (!!test.data && !isTerminal(state))}>
          Prova
        </Button>
      </form>
      {outcome}
    </div>
  )
}
