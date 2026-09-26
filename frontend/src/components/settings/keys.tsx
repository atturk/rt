import { Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import { useSavePricing, useSaveSecret, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { Tooltip } from '@/components/ui/tooltip'
import { EXTRA_SECRETS, pricingToRows, providerLabel, rowsToPricing, type Pricing, type PricingRow } from '@/lib/settings'
import { SaveFeedback, SecretBadge, Section } from './common'
import { CredentialTest } from './models'

// ------------------------------------------------------------------ chiavi

type SecretEntry = { name: string; label: string; set: boolean; credential?: string }

function secretEntries(settings: Settings): SecretEntry[] {
  const entries: SecretEntry[] = settings.credentials
    .filter((c) => c.env_var)
    .map((c) => ({ name: c.env_var, label: `${c.name} (${providerLabel(c.provider)})`, set: c.set, credential: c.name }))
  entries.push(
    { ...EXTRA_SECRETS[0], set: settings.telegram.bot_token_set },
    { ...EXTRA_SECRETS[1], set: settings.transcription.api_key_set },
  )
  return entries
}

export function SecretsSection({ settings }: { settings: Settings }) {
  return (
    <Section
      id="chiavi"
      title="Chiavi"
      description={
        <>
          Le chiavi si possono solo scrivere: la pagina mostra se sono impostate, mai il valore. Sono salvate{' '}
          {settings.secrets_encrypted ? "nell'archivio cifrato di RT" : 'nel file .env (rt secrets init le sposta in un archivio cifrato)'}.
        </>
      }
    >
      <div className="flex flex-col divide-y">
        {secretEntries(settings).map((entry) => (
          <SecretRow key={entry.name} entry={entry} settings={settings} />
        ))}
      </div>
    </Section>
  )
}

function SecretRow({ entry, settings }: { entry: SecretEntry; settings: Settings }) {
  const save = useSaveSecret()
  const [value, setValue] = useState('')
  const inputId = `segreto-${entry.name}`
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate({ name: entry.name, value: value.trim() }, { onSuccess: () => setValue('') })
  }
  return (
    <div className="flex flex-col gap-2 py-3 first:pt-0" data-testid="secret-row" data-name={entry.name}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={inputId} className="text-sm font-semibold">
          {entry.label}
        </label>
        <SecretBadge set={entry.set} />
        <code className="text-[11px] text-muted-foreground">{entry.name}</code>
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
      </form>
      <SaveFeedback mutation={save} success="Chiave salvata." />
      {entry.credential && <CredentialTest credential={entry.credential} settings={settings} />}
    </div>
  )
}

// ------------------------------------------------------------------ pricing

export function PricingSection({ settings }: { settings: Settings }) {
  const save = useSavePricing()
  const [formError, setFormError] = useState<string | null>(null)
  const providers = unique(settings.connections.map((c) => c.provider))
  const models = unique(settings.phases.map((p) => p.model ?? ''))
  return (
    <Section
      id="pricing"
      title="Pricing"
      description="Prezzi in USD per 1 milione di token, per i modelli che mancano dal listino di RT o che vuoi correggere. Servono a stimare i costi; la stima non considera il caching dei token, quindi il costo reale può essere più basso."
    >
      <PricingFields
        key={JSON.stringify(settings.pricing)}
        pricing={settings.pricing as Pricing}
        providers={providers}
        models={models}
        pending={save.isPending}
        onSubmit={(rows) => {
          try {
            const body = rowsToPricing(rows)
            setFormError(null)
            save.mutate(body)
          } catch (err) {
            setFormError((err as Error).message)
          }
        }}
      />
      {formError && <Alert tone="danger">{formError}</Alert>}
      {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      {save.isSuccess && !formError && <p role="status" className="text-xs text-success">Pricing salvato.</p>}
    </Section>
  )
}

function unique(values: string[]): string[] {
  return [...new Set(values.map((v) => v.trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

const EMPTY_ROW: PricingRow = { provider: '', model: '', input: '', output: '', reasoning: '' }

const PRICE_COLUMNS = [
  { key: 'input', label: 'IN', hint: 'Costo per milione di token in input' },
  { key: 'output', label: 'OUT', hint: 'Costo per milione di token in output' },
  { key: 'reasoning', label: 'R', hint: 'Costo per milione di token di ragionamento (se il provider lo fa pagare a parte)' },
] as const

const ROW_GRID = 'sm:grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_5.5rem_5.5rem_5.5rem_auto]'

function PricingFields({
  pricing,
  providers,
  models,
  pending,
  onSubmit,
}: {
  pricing: Pricing
  providers: string[]
  models: string[]
  pending: boolean
  onSubmit: (rows: PricingRow[]) => void
}) {
  const [rows, setRows] = useState<PricingRow[]>(() => {
    const saved = pricingToRows(pricing)
    return saved.length ? saved : [{ ...EMPTY_ROW }]
  })
  function update(i: number, patch: Partial<PricingRow>) {
    setRows((c) => c.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  }
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(rows)
      }}
    >
      <datalist id="pricing-providers">
        {providers.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
      <datalist id="pricing-models">
        {models.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
      <div className={`hidden items-end gap-2 text-xs font-semibold text-muted-foreground ${ROW_GRID}`}>
        <span>Provider</span>
        <span>Modello</span>
        {PRICE_COLUMNS.map((c) => (
          <Tooltip key={c.key} id={`pricing-tip-${c.key}`} content={c.hint}>
            <span tabIndex={0} aria-describedby={`pricing-tip-${c.key}`} className="cursor-help underline decoration-dotted underline-offset-2">
              {c.label}
            </span>
          </Tooltip>
        ))}
        <span />
      </div>
      {rows.map((row, i) => (
        <div key={i} className={`flex flex-wrap items-center gap-2 ${ROW_GRID}`} data-testid="pricing-row">
          <SuggestedInput
            label={`Provider ${i + 1}`}
            placeholder="Provider"
            list="pricing-providers"
            value={row.provider}
            known={providers}
            warning="Provider non configurato"
            onChange={(v) => update(i, { provider: v })}
          />
          <SuggestedInput
            label={`Modello ${i + 1}`}
            placeholder="Modello"
            list="pricing-models"
            value={row.model}
            known={models}
            warning="Modello non in uso"
            onChange={(v) => update(i, { model: v })}
          />
          {PRICE_COLUMNS.map((c) => (
            <Input
              key={c.key}
              aria-label={`${c.label} ${i + 1}`}
              aria-describedby={`pricing-tip-${c.key}`}
              title={c.hint}
              placeholder={c.label}
              className="w-[5.5rem] sm:w-full"
              inputMode="decimal"
              value={row[c.key]}
              onChange={(e) => update(i, { [c.key]: e.target.value })}
            />
          ))}
          <Button variant="ghost" size="icon" aria-label={`Rimuovi riga ${i + 1}`} onClick={() => setRows((c) => c.filter((_, j) => j !== i))}>
            <Trash2 />
          </Button>
        </div>
      ))}
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => setRows((c) => [...c, { ...EMPTY_ROW }])}>
          <Plus /> Aggiungi modello
        </Button>
      </div>
      <div>
        <Button type="submit" disabled={pending}>
          Salva pricing
        </Button>
      </div>
    </form>
  )
}

/** Campo con suggerimenti (datalist). Un valore fuori dall'elenco mostra un'icona di avviso a
 * sinistra, dentro il campo: è solo un avviso, il salvataggio resta possibile. */
function SuggestedInput({
  label,
  placeholder,
  list,
  value,
  known,
  warning,
  onChange,
}: {
  label: string
  placeholder: string
  list: string
  value: string
  known: string[]
  warning: string
  onChange: (value: string) => void
}) {
  const id = useId()
  const warn = !!value.trim() && !known.includes(value.trim())
  const tipId = `${id}-avviso`
  return (
    <div className="group/field relative min-w-40 flex-1" data-warning={warn ? '' : undefined}>
      <Input
        aria-label={label}
        aria-describedby={warn ? tipId : undefined}
        placeholder={placeholder}
        list={list}
        autoComplete="off"
        value={value}
        className={warn ? 'pl-8' : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {warn && (
        <Tooltip
          id={tipId}
          content={warning}
          className="absolute left-2 top-1/2 -translate-y-1/2"
          bubbleClassName="group-focus-within/field:block"
        >
          <TriangleAlert className="size-4 text-warning" role="img" aria-label={warning} data-testid="field-warning" />
        </Tooltip>
      )}
    </div>
  )
}
