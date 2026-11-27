import { Check } from 'lucide-react'
import { useId, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useDismissNotice } from '@/api/documentEdit'
import {
  useAssignAllPhases,
  useAssignPhase,
  useConnectionCatalog,
  useCostEstimate,
  type CatalogModel,
  type Settings,
} from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { SettingsDisclosure, SettingsInfoButton, SettingsRow, SettingsSelect as Select } from './ui'
import { NewConnectionForm, PhaseRows } from './models'
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
        {step === 2 && <ModelsStep settings={settings} onBack={() => go(1)} onDone={next} />}
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

function formatTokenPrice(price: number | null | undefined): string | null {
  if (price == null || !Number.isFinite(price)) return null
  const formatted = price >= 10 ? price.toFixed(2) : Number(price.toFixed(4)).toString()
  return `$${formatted} / M token`
}

function ModelCombobox({
  id,
  ariaLabel,
  items,
  value,
  selectedModel,
  onInputChange,
  onSelect,
  freeField = false,
  loading = false,
  placeholder = 'Cerca o scegli un modello…',
}: {
  id: string
  ariaLabel?: string
  items: CatalogModel[]
  value: string
  selectedModel: string
  onInputChange: (text: string) => void
  onSelect: (modelId: string) => void
  freeField?: boolean
  loading?: boolean
  placeholder?: string
}) {
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const [typing, setTyping] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  const query = typing ? value.trim().toLowerCase() : ''
  const filtered = items
    .filter((item) => !query || item.id.toLowerCase().includes(query) || item.name.toLowerCase().includes(query))
    .slice(0, 50)
  const clampedActive = filtered.length > 0 ? Math.min(activeIndex, filtered.length - 1) : -1

  function choose(modelId: string) {
    onSelect(modelId)
    setTyping(false)
    setOpen(false)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        setActiveIndex(0)
      } else if (filtered.length > 0) {
        setActiveIndex((i) => (i + 1) % filtered.length)
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        setActiveIndex(Math.max(0, filtered.length - 1))
      } else if (filtered.length > 0) {
        setActiveIndex((i) => (i - 1 + filtered.length) % filtered.length)
      }
    } else if (e.key === 'Enter') {
      if (open && clampedActive >= 0 && filtered[clampedActive]) {
        e.preventDefault()
        choose(filtered[clampedActive].id)
      } else if (freeField && value.trim()) {
        e.preventDefault()
        choose(value.trim())
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
      }
    }
  }

  return (
    <div
      className="relative"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setOpen(false)
          setTyping(false)
        }
      }}
    >
      <Input
        id={id}
        role="combobox"
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open && clampedActive >= 0 ? `${listboxId}-opt-${clampedActive}` : undefined}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        className="h-11 w-full"
        value={value}
        placeholder={loading ? 'Carico i modelli…' : placeholder}
        onFocus={() => {
          setOpen(true)
          setActiveIndex(0)
        }}
        onClick={() => setOpen(true)}
        onChange={(e) => {
          setTyping(true)
          setOpen(true)
          setActiveIndex(0)
          onInputChange(e.target.value)
        }}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border bg-card p-1 shadow-panel"
        >
          {loading && filtered.length === 0 && (
            <li className="px-3 py-2 text-meta text-muted-foreground">Caricamento elenco modelli…</li>
          )}
          {!loading && filtered.length === 0 && (
            <li className="px-3 py-2 text-meta text-muted-foreground">
              {freeField ? 'Nessun modello in elenco: premi Invio o Continua per usare questo ID.' : 'Nessun modello trovato.'}
            </li>
          )}
          {filtered.map((item, idx) => {
            const isActive = idx === clampedActive
            const isSelected = item.id === selectedModel
            const priceLabel = formatTokenPrice(item.prompt_price)
            return (
              <li
                key={item.id}
                id={`${listboxId}-opt-${idx}`}
                role="option"
                aria-selected={isSelected || isActive}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActiveIndex(idx)}
                onClick={() => choose(item.id)}
                className={cn(
                  'flex cursor-pointer items-center justify-between gap-2 rounded-md px-3 py-2 text-body',
                  isActive ? 'bg-muted text-foreground' : 'hover:bg-muted/60',
                )}
              >
                <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="truncate font-medium">{item.name}</span>
                  {item.name !== item.id && <span className="truncate text-meta text-muted-foreground">{item.id}</span>}
                  {item.recommended && <Badge tone="success">Consigliato</Badge>}
                </span>
                {priceLabel && <span className="shrink-0 text-meta tabular-nums text-muted-foreground">{priceLabel}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

const OPTIONAL_MODEL_ROWS: ReadonlyArray<{ job: 'image_description' | 'enrichment_image'; label: string; info: string }> = [
  {
    job: 'image_description',
    label: 'Descrizione immagini',
    info: 'Serve solo per leggere foto e pagine dei PDF. Se non lo imposti, quando caricherai immagini RT ti porterà qui per sceglierlo.',
  },
  {
    job: 'enrichment_image',
    label: 'Generazione immagini',
    info: "Serve solo per creare immagini nell'arricchimento. Se non lo imposti, RT te lo chiederà quando serve.",
  },
]

function ModelsStep({ settings, onBack, onDone }: { settings: Settings; onBack: () => void; onDone: () => void }) {
  const [params, setParams] = useSearchParams()
  const [perPhase, setPerPhase] = useState(params.get('modelli') === 'per-fase')
  const assignAll = useAssignAllPhases()
  const assignOptional = useAssignPhase()

  const firstAssigned = settings.phases.find((p) => p.connection && !OPTIONAL_JOBS.has(p.job)) ?? null
  const [connection, setConnection] = useState(firstAssigned?.connection ?? settings.connections[0]?.name ?? '')
  const selectedConn = settings.connections.find((c) => c.name === connection) ?? settings.connections[0]

  const initialModel = firstAssigned?.model ?? ''
  const [inputValue, setInputValue] = useState(initialModel)
  const [selectedModel, setSelectedModel] = useState(initialModel)
  const [useForAll, setUseForAll] = useState(true)

  const [editingOptional, setEditingOptional] = useState<'image_description' | 'enrichment_image' | null>(null)
  const [optInput, setOptInput] = useState('')
  const [optSelected, setOptSelected] = useState('')

  const catalog = useConnectionCatalog(selectedConn?.name)
  const fallbackMode = catalog.isError || Boolean(catalog.data?.fallback)
  const catalogItems: CatalogModel[] = catalog.data?.items?.length
    ? catalog.data.items
    : (selectedConn?.models ?? []).map((id) => ({
        id,
        name: id,
        prompt_price: null,
        completion_price: null,
        recommended: false,
      }))

  const effectiveMainModel = fallbackMode ? inputValue.trim() : selectedModel
  const estimate = useCostEstimate(selectedConn?.provider, effectiveMainModel || undefined)

  function setMode(next: boolean) {
    setPerPhase(next)
    const updated = new URLSearchParams(params)
    if (next) updated.set('modelli', 'per-fase')
    else updated.delete('modelli')
    setParams(updated, { replace: true })
  }

  function handleConnectionChange(nextConn: string) {
    setConnection(nextConn)
    setInputValue('')
    setSelectedModel('')
    setEditingOptional(null)
  }

  function handleContinue() {
    if (!selectedConn) return
    if (useForAll && effectiveMainModel) {
      const jobs = settings.phases.filter((p) => !['image_description', 'enrichment_image'].includes(p.job)).map((p) => p.job)
      assignAll.mutate({ jobs, connection: selectedConn.name, model: effectiveMainModel }, { onSuccess: onDone })
      return
    }
    if (stepDone(settings, 1)) {
      onDone()
    }
  }

  if (settings.connections.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="warning">Crea prima una connessione nel passo precedente.</Alert>
        <div>
          <Button variant="outline" className="h-11" onClick={onBack}>
            Indietro
          </Button>
        </div>
      </div>
    )
  }

  const canContinue = useForAll ? Boolean(effectiveMainModel) : stepDone(settings, 1)
  const mutationError = assignAll.isError
    ? errorMessage(assignAll.error)
    : assignOptional.isError
      ? errorMessage(assignOptional.error)
      : null

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h2 className="text-heading font-semibold tracking-tight">Scegli il modello</h2>
        <p className="text-body text-muted-foreground">
          Ne basta uno: RT lo usa per tutte le fasi di elaborazione. Puoi cambiarlo quando vuoi dalle Impostazioni.
        </p>
      </header>

      {settings.connections.length > 1 && (
        <div className="rounded-lg border">
          <SettingsRow
            label="Connessione"
            htmlFor="wizard-connection"
            control={
              <Select id="wizard-connection" className="w-full @sm:w-60" value={connection} onChange={(e) => handleConnectionChange(e.target.value)}>
                {settings.connections.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </Select>
            }
          />
        </div>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor="wizard-main-model" className="text-body font-medium text-foreground">
          Modello principale <span className="text-danger" aria-hidden>*</span>
        </label>
        <ModelCombobox
          id="wizard-main-model"
          items={catalogItems}
          value={inputValue}
          selectedModel={selectedModel}
          freeField={fallbackMode}
          loading={catalog.isPending}
          onInputChange={(text) => {
            setInputValue(text)
            if (text !== selectedModel) setSelectedModel('')
          }}
          onSelect={(modelId) => {
            setInputValue(modelId)
            setSelectedModel(modelId)
          }}
        />
        {fallbackMode && (
          <p className="text-meta text-muted-foreground">
            Elenco online non disponibile: puoi scegliere tra i modelli già noti o inserire un identificativo manualmente.
          </p>
        )}
        {effectiveMainModel && estimate.data?.cost_eur != null && (
          <p className="text-meta text-muted-foreground" data-testid="wizard-cost-estimate">
            Costo stimato per una lezione di 2 ore: <strong className="font-semibold text-foreground">{estimate.data.formatted}</strong>
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="inline-flex items-center gap-2 text-body cursor-pointer">
          <input
            type="checkbox"
            className="size-4 accent-current"
            checked={useForAll}
            onChange={(e) => setUseForAll(e.target.checked)}
          />
          Usa questo modello per tutte le fasi
        </label>
        <button
          type="button"
          onClick={() => setMode(!perPhase)}
          className="text-meta font-medium text-link hover:underline cursor-pointer"
        >
          Personalizza per fase
        </button>
      </div>

      {perPhase && (
        <div className="rounded-lg border">
          <PhaseRows settings={settings} />
        </div>
      )}

      <section className="rounded-lg border bg-muted/20" aria-label="Modelli facoltativi">
        <div className="border-b px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          FACOLTATIVI · puoi aggiungerli anche dopo
        </div>
        <div className="divide-y divide-border/60">
          {OPTIONAL_MODEL_ROWS.map((row) => {
            const phase = settings.phases.find((p) => p.job === row.job)
            const isEditing = editingOptional === row.job
            const savedModel = phase?.model ?? null
            return (
              <div key={row.job} className="flex flex-col gap-2 px-4 py-3" data-testid={`optional-model-${row.job}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1 text-body font-medium text-foreground">
                    {row.label}
                    <SettingsInfoButton label={row.label} info={row.info} />
                  </span>
                  <div className="flex items-center gap-2 text-meta">
                    {savedModel ? (
                      <>
                        <span className="font-medium text-foreground">{savedModel}</span>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingOptional(isEditing ? null : row.job)
                            setOptInput(savedModel)
                            setOptSelected(savedModel)
                          }}
                          className="font-medium text-link hover:underline cursor-pointer"
                        >
                          {isEditing ? 'Chiudi' : 'Cambia'}
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="text-muted-foreground">Non impostato ·</span>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingOptional(isEditing ? null : row.job)
                            setOptInput('')
                            setOptSelected('')
                          }}
                          className="font-medium text-link hover:underline cursor-pointer"
                        >
                          {isEditing ? 'Chiudi' : 'Aggiungi'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {isEditing && (
                  <ModelCombobox
                    id={`wizard-optional-${row.job}`}
                    ariaLabel={`Modello per ${row.label}`}
                    items={catalogItems}
                    value={optInput}
                    selectedModel={optSelected}
                    freeField={fallbackMode}
                    loading={catalog.isPending}
                    onInputChange={(text) => {
                      setOptInput(text)
                      if (text !== optSelected) setOptSelected('')
                    }}
                    onSelect={(modelId) => {
                      setOptInput(modelId)
                      setOptSelected(modelId)
                      if (selectedConn) {
                        assignOptional.mutate(
                          { job: row.job, connection: selectedConn.name, model: modelId, batch: false },
                          { onSuccess: () => setEditingOptional(null) },
                        )
                      }
                    }}
                  />
                )}
              </div>
            )
          })}
        </div>
      </section>

      {mutationError && <Alert tone="danger">{mutationError}</Alert>}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button type="button" variant="outline" className="h-11" onClick={onBack}>
          Indietro
        </Button>
        <Button
          type="button"
          className="h-11 px-6"
          disabled={!canContinue || assignAll.isPending || assignOptional.isPending}
          onClick={handleContinue}
        >
          Continua
        </Button>
      </div>
    </div>
  )
}
