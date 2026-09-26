import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import { useSavePricing, useSaveSecret, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
        <Input
          id={inputId}
          type="password"
          autoComplete="off"
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
  return (
    <Section
      id="pricing"
      title="Pricing"
      description="Prezzi in USD per 1 milione di token, per i modelli che mancano dal listino di RT o che vuoi correggere. Servono a stimare i costi."
    >
      <PricingFields
        key={JSON.stringify(settings.pricing)}
        pricing={settings.pricing as Pricing}
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

const EMPTY_ROW: PricingRow = { provider: '', model: '', input: '', output: '', reasoning: '' }

function PricingFields({ pricing, pending, onSubmit }: { pricing: Pricing; pending: boolean; onSubmit: (rows: PricingRow[]) => void }) {
  const [rows, setRows] = useState<PricingRow[]>(() => {
    const saved = pricingToRows(pricing)
    return saved.length ? saved : [{ ...EMPTY_ROW }]
  })
  function update(i: number, patch: Partial<PricingRow>) {
    setRows((c) => c.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  }
  const cols: { key: keyof PricingRow; label: string; className?: string }[] = [
    { key: 'provider', label: 'Provider' },
    { key: 'model', label: 'Modello' },
    { key: 'input', label: 'Input', className: 'w-24' },
    { key: 'output', label: 'Output', className: 'w-24' },
    { key: 'reasoning', label: 'Reasoning', className: 'w-24' },
  ]
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(rows)
      }}
    >
      {rows.map((row, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 sm:flex-nowrap" data-testid="pricing-row">
          {cols.map((c) => (
            <Input
              key={c.key}
              aria-label={`${c.label} ${i + 1}`}
              placeholder={c.label}
              className={c.className}
              inputMode={c.className ? 'decimal' : undefined}
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
