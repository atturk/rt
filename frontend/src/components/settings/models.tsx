import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import {
  isTerminal,
  useAddModel,
  useAssignPhase,
  useCreateConnection,
  useJob,
  useRoute,
  useSaveRoute,
  useTestCredential,
  type RouteOut,
  type Settings,
} from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { PROVIDERS, ROUTE_ROLES, defaultBaseUrl, providerLabel, type Provider } from '@/lib/settings'
import { Checkbox, Field, SaveFeedback, SecretBadge, Section } from './common'

type Connection = Settings['connections'][number]
type Phase = Settings['phases'][number]

// ------------------------------------------------------------------ modelli per fase

export function PhasesSection({ settings }: { settings: Settings }) {
  return (
    <Section
      id="fasi"
      title="Modelli per fase"
      description="Connessione e modello usati da ciascuna delle sei fasi. Un modello nuovo viene aggiunto alla connessione."
    >
      {settings.connections.length === 0 && <Alert tone="warning">Crea prima una connessione qui sotto.</Alert>}
      <div className="flex flex-col divide-y">
        {settings.phases.map((phase) => (
          <PhaseRow key={`${phase.job}:${phase.connection ?? ''}:${phase.model ?? ''}`} phase={phase} connections={settings.connections} />
        ))}
      </div>
    </Section>
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
      className="grid grid-cols-1 items-end gap-2 py-3 first:pt-0 sm:grid-cols-[10rem_1fr_1fr_auto]"
      data-testid="phase-row"
      data-job={phase.job}
      aria-label={`Fase ${phase.label}`}
    >
      <div className="flex flex-col gap-1 self-center">
        <span className="text-sm font-semibold">{phase.label}</span>
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
      {assign.isError && (
        <Alert tone="danger" className="sm:col-span-4">
          {errorMessage(assign.error)}
        </Alert>
      )}
    </form>
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
            <Input
              id={`conn-key-${i}`}
              type="password"
              autoComplete="off"
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
        {test.data.worker_available ? 'Prova in corso…' : 'Nessun worker attivo: la prova resta in coda finché non avvii rt worker.'}
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
