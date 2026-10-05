import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import { useDeleteSecret, useSavePricing, useSaveSecret, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { useOptionKey } from '@/lib/optionKey'
import { pricingToRows, providerLabel, rowsToPricing, type Pricing, type PricingRow } from '@/lib/settings'
import { SaveFeedback, SecretBadge, Section } from './common'
import { CredentialTest } from './models'
import { useQueryClient } from '@tanstack/react-query'

// ------------------------------------------------------------------ chiavi

type SecretEntry = { name: string; label: string; set: boolean; credential?: string }

function secretEntries(settings: Settings): SecretEntry[] {
  const entries: SecretEntry[] = settings.credentials
    .filter((c) => c.env_var)
    .map((c) => ({ name: c.env_var, label: `${c.name} (${providerLabel(c.provider)})`, set: c.set, credential: c.name }))
  return entries
}

export function SecretsSection({ settings, connection }: { settings: Settings; connection: Settings['connections'][number] }) {
  return (
    <Section
      id={`chiavi-${connection.name}`}
      title="Chiavi"
      description={
        <>
          Le chiavi si possono solo scrivere: la pagina mostra se sono impostate, mai il valore. Sono salvate{' '}
          {settings.secrets_encrypted ? "nell'archivio cifrato di RT" : "in un file non cifrato (.env) sul Mac: l'installazione di RT le sposta in un archivio cifrato"}.
        </>
      }
    >
      <div className="flex flex-col divide-y">
        {secretEntries(settings).filter(e => connection.credentials.some(c => c.name === e.credential)).map((entry) => (
          <SecretRow key={entry.name} entry={entry} settings={settings} />
        ))}
      </div>
    </Section>
  )
}

function SecretRow({ entry, settings }: { entry: SecretEntry; settings: Settings }) {
  const save = useSaveSecret()
  const deletion = useDeleteSecret()
  const optionDown = useOptionKey()
  const [confirm, setConfirm] = useState(false)
  const [value, setValue] = useState('')
  const inputId = `segreto-${entry.name}`
  function submit(e: FormEvent) {
    e.preventDefault()
    deletion.reset()
    save.mutate({ name: entry.name, value: value.trim() }, { onSuccess: () => setValue('') })
  }
  // Con Option premuto "Prova" diventa "Elimina" (nelle righe senza Prova compare accanto a Salva).
  const remove = optionDown && entry.set ? (
    <Button type="button" variant="destructive" aria-label={`Elimina ${entry.label}`}
      onClick={() => { save.reset(); deletion.reset(); setConfirm(true) }}>
      Elimina
    </Button>
  ) : undefined
  return (
    <div className="flex flex-col gap-2 py-3 first:pt-0" data-testid="secret-row" data-name={entry.name}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={inputId} className="text-body font-semibold">
          {entry.label}
        </label>
        <SecretBadge set={entry.set} />
        <code className="text-meta text-muted-foreground">{entry.name}</code>
      </div>
      <form className="flex gap-2" onSubmit={submit}>
        <SecretInput
          id={inputId}
          value={value}
          placeholder={entry.set ? 'Nuovo valore (sostituisce quello salvato)' : 'Incolla la chiave'}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button type="submit" disabled={!value.trim() || save.isPending}>
          Salva
        </Button>
        {!entry.credential && remove}
      </form>
      <SaveFeedback mutation={save} success="Chiave salvata." />
      {deletion.isSuccess && <p role="status" className="text-meta text-success">Chiave eliminata.</p>}
      {entry.credential && <CredentialTest credential={entry.credential} settings={settings} action={remove} />}
      <ConfirmDialog open={confirm} title="Elimina chiave" confirmLabel="Elimina"
        confirmDisabled={deletion.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => deletion.mutate(entry.name, { onSuccess: () => setConfirm(false) })}>
        <p>Eliminare la chiave di «{entry.label}» ({entry.name})?</p>
        <p className="mt-2 text-meta text-muted-foreground">
          Viene tolta dall'archivio di RT e da .env. Ciò che la usa smette di funzionare finché non ne salvi una nuova.
        </p>
        {deletion.isError && <Alert tone="danger" className="mt-3">{errorMessage(deletion.error)}</Alert>}
      </ConfirmDialog>
    </div>
  )
}


/** Il listino è per provider/modello: ogni prezzo ha una sola connessione proprietaria nella pagina. */
function ownedModels(settings: Settings, connection: Settings['connections'][number]): string[] {
  const connections = settings.connections.filter(c => c.provider === connection.provider)
  const models = new Set([...connection.models, ...Object.keys(settings.pricing?.[connection.provider] ?? {})])
  if (!connections.length) return [...models]
  return [...models].filter(model => (connections.find(c => c.models.includes(model)) ?? connections[0])?.name === connection.name)
}

export function PricingSection({ settings, connection }: { settings: Settings; connection: Settings['connections'][number] }) {
  const save = useSavePricing()
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const models = ownedModels(settings, connection)
  const pricing = Object.fromEntries(Object.entries(settings.pricing?.[connection.provider] ?? {}).filter(([model]) => models.includes(model)))
  const [rows, setRows] = useState<PricingRow[]>(() => {
    const saved = pricingToRows({ [connection.provider]: pricing } as Pricing)
    return saved.length ? saved : [{ provider: connection.provider, model: '', input: '', output: '', reasoning: '' }]
  })
  const update = (i: number, patch: Partial<PricingRow>) => setRows(old => old.map((row, j) => i === j ? { ...row, ...patch } : row))
  function submit(e: FormEvent) {
    e.preventDefault()
    try {
      const changes = rowsToPricing(rows.filter(r => r.model.trim() || r.input || r.output || r.reasoning))
      const latest = client.getQueryData<Settings>(['settings']) ?? settings
      const rest = { ...latest.pricing[connection.provider] }
      for (const model of models) delete rest[model]
      setError(null)
      save.mutate({ ...latest.pricing, [connection.provider]: { ...rest, ...changes[connection.provider] } })
    } catch (err) { setError(errorMessage(err)) }
  }
  return <Section id={`costi-${connection.name}`} title="Costi per modello">
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label={`Costi di ${connection.name}`}>
      <p className="text-meta text-muted-foreground">USD per milione di token · input, output, ragionamento</p>
      {rows.map((row, i) => <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1fr)_5rem_5rem_5rem_auto]" data-testid="pricing-row">
        <Input aria-label={`Modello costo ${i + 1}`} value={row.model} placeholder="Modello" list={`modelli-costo-${connection.name}`} onChange={e => update(i, { model: e.target.value })} />
        {(['input', 'output', 'reasoning'] as const).map((column, j) => <Input key={column} aria-label={`${['IN', 'OUT', 'R'][j]} ${i + 1}`} inputMode="decimal" placeholder={['IN', 'OUT', 'R'][j]} value={row[column]} onChange={e => update(i, { [column]: e.target.value })} />)}
        <Button variant="ghost" size="icon" aria-label={`Rimuovi costo ${i + 1}`} onClick={() => setRows(old => old.filter((_, j) => i !== j))}><Trash2 /></Button>
      </div>)}
      <datalist id={`modelli-costo-${connection.name}`}>{connection.models.map(model => <option key={model} value={model} />)}</datalist>
      <div className="flex gap-2"><Button variant="outline" onClick={() => setRows(old => [...old, { provider: connection.provider, model: '', input: '', output: '', reasoning: '' }])}><Plus />Aggiungi costo</Button>
        <Button type="submit" disabled={save.isPending}>Salva costi</Button></div>
    </form>
    {error && <Alert tone="danger">{error}</Alert>}<SaveFeedback mutation={save} />
  </Section>
}

/** Le chiavi STT e Telegram si eliminano nel loro unico form, con Option come prima. */
export function ExtraSecretDelete({ name, label, set }: { name: string; label: string; set: boolean }) {
  const option = useOptionKey()
  const remove = useDeleteSecret()
  const [confirm, setConfirm] = useState(false)
  return <>
    {set && option && <Button type="button" variant="destructive" size="sm" aria-label={`Elimina ${label}`} onClick={() => setConfirm(true)}>Elimina</Button>}
    <ConfirmDialog open={confirm} title={`Elimina ${label}`} confirmLabel="Elimina" confirmDisabled={remove.isPending} onCancel={() => setConfirm(false)}
      onConfirm={() => remove.mutate(name, { onSuccess: () => setConfirm(false) })}>
      <p>Eliminare {label} dall’archivio di RT?</p>{remove.isError && <Alert tone="danger">{errorMessage(remove.error)}</Alert>}
    </ConfirmDialog>
    {remove.isSuccess && <p role="status" className="text-meta text-success">Chiave eliminata.</p>}
  </>
}
