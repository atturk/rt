import { useState, type FormEvent } from 'react'

import { useSaveTranscription, type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { isAppWindow } from '@/lib/zoom'
import { SettingsSelect as Select } from './common'
import { Field, SaveFeedback, SecretBadge, Section } from './common'
import { useGeneralPreference } from './useGeneralPreference'

import { ExtraSecretDelete } from './keys'
import { SettingsGroup, SettingsInfoButton } from './ui'

/** I form sono inizializzati dai valori salvati e rimontati (key) quando il backend cambia:
 * dopo ogni salvataggio si vede quello che l'API ha scritto, non quello che si era digitato. */

export function TranscriptionSection({ settings }: { settings: Settings }) {
  const save = useSaveTranscription()
  const t = settings.transcription
  return (
    <Section id="trascrizione" title="Trascrizione" description="Motore usato per trascrivere l'audio delle lezioni e le risposte vocali.">
      <TranscriptionFields key={JSON.stringify(t)} settings={settings} pending={save.isPending} onSubmit={(body) => save.mutate(body)} />
      <SaveFeedback mutation={save} />
    </Section>
  )
}

type Engine = 'macparakeet' | 'parakeet' | 'custom'

const ENGINE_LABEL: Record<Engine, string> = {
  macparakeet: 'macparakeet (sul Mac)',
  parakeet: 'Parakeet ONNX (locale)',
  custom: 'Server OpenAI-compatible',
}

function engineHint(t: Settings['transcription'], engine: Engine): string {
  if (engine === 'macparakeet') {
    if (!t.macparakeet_available) return 'macparakeet funziona solo su macOS: qui scegli Parakeet ONNX.'
    return t.macparakeet_installed ? 'Usa il Neural Engine del Mac: il più veloce.' : 'macparakeet-cli non è installato su questo Mac.'
  }
  if (engine === 'parakeet') {
    if (!t.parakeet_available) return 'Il motore non è installato: reinstalla RT.'
    return t.parakeet_model_ready
      ? 'Gira su questo computer, senza internet.'
      : 'Gira su questo computer. Il modello (circa 700 MB) si scarica alla prima trascrizione, poi funziona senza internet.'
  }
  return 'Un tuo server di trascrizione, con risposta verbose_json e segmenti temporizzati.'
}

function TranscriptionFields({
  settings,
  pending,
  onSubmit,
}: {
  settings: Settings
  pending: boolean
  onSubmit: (body: { engine: Engine; base_url: string; model: string; api_key: string | null }) => void
}) {
  const t = settings.transcription
  const [engine, setEngine] = useState<Engine>(t.engine as Engine)
  const [baseUrl, setBaseUrl] = useState(t.base_url ?? '')
  const [model, setModel] = useState(t.model ?? '')
  const [apiKey, setApiKey] = useState('')
  const custom = engine === 'custom'
  const engines: Engine[] = t.macparakeet_available || t.engine === 'macparakeet' ? ['macparakeet', 'parakeet', 'custom'] : ['parakeet', 'custom']
  function submit(e: FormEvent) {
    e.preventDefault()
    onSubmit({ engine, base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() || null })
  }
  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={submit}>
      <Field label="Motore" htmlFor="stt-engine" hint={<span data-testid="stt-engine-hint">{engineHint(t, engine)}</span>}>
        <Select id="stt-engine" value={engine} onChange={(e) => setEngine(e.target.value as Engine)}>
          {engines.map((name) => (
            <option key={name} value={name}>
              {ENGINE_LABEL[name]}
              {name === t.recommended ? ' · consigliato' : ''}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Base URL del server" htmlFor="stt-base-url">
        <Input id="stt-base-url" value={baseUrl} disabled={!custom} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:8000/v1" />
      </Field>
      <Field label="Modello" htmlFor="stt-model">
        <Input id="stt-model" value={model} disabled={!custom} onChange={(e) => setModel(e.target.value)} placeholder="whisper-1" />
      </Field>
      <Field label="Chiave API (facoltativa)" htmlFor="stt-key" hint={<>Chiave: <SecretBadge set={t.api_key_set} /><ExtraSecretDelete name="RT_STT_API_KEY" label="chiave STT" set={t.api_key_set} /></>}>
        <SecretInput
          id="stt-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={t.api_key_set ? 'Lascia vuoto per mantenere quella salvata' : ''}
        />
      </Field>
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          Salva trascrizione
        </Button>
      </div>
    </form>
  )
}

type CloseAction = 'background' | 'esci'

const CLOSE_OPTIONS: ReadonlyArray<{ value: CloseAction; label: string; hint: string }> = [
  {
    value: 'background',
    label: 'Continua a lavorare in background (consigliato)',
    hint: 'RT finisce i job in corso e riceve le risposte dei provider IA che lavorano in modalità batch, più economica ma più lenta.',
  },
  {
    value: 'esci',
    label: 'Chiudi del tutto RT',
    hint: 'Ogni volta che premi la X RT smette di lavorare in background, come con Esci da RT (⌘Q). I job in corso si fermano e riprendono alla prossima apertura.',
  },
]

export function CloseActionSection({ settings }: { settings: Settings }) {
  const save = useGeneralPreference()
  const [confirmQuit, setConfirmQuit] = useState(false)
  if (!isAppWindow()) return null
  const current: CloseAction = settings.preferences?.chiusura_x === 'esci' ? 'esci' : 'background'

  function select(next: CloseAction) {
    if (next === current) return
    if (next === 'esci') {
      setConfirmQuit(true)
      return
    }
    save.mutate({ chiusura_x: next })
  }

  return (
    <SettingsGroup id="chiusura-finestra" title="Chiudendo la finestra con la X">
      <div role="radiogroup" aria-label="Chiudendo la finestra con la X" className="divide-y divide-border/60">
        {CLOSE_OPTIONS.map((opt) => (
          <div key={opt.value} className="flex min-h-12 items-center justify-between gap-3 px-4 py-3">
            <label className="flex flex-1 cursor-pointer items-center gap-3">
              <input
                type="radio"
                name="chiusura_x"
                value={opt.value}
                checked={current === opt.value}
                disabled={save.isPending}
                onChange={() => select(opt.value)}
                className="size-4 shrink-0 accent-primary"
              />
              <span className="text-body text-foreground">{opt.label}</span>
            </label>
            <SettingsInfoButton label={opt.label} info={opt.hint} />
          </div>
        ))}
      </div>
      {save.isError && (
        <div className="px-4 py-3">
          <SaveFeedback mutation={save} />
        </div>
      )}
      <ConfirmDialog
        open={confirmQuit}
        title="Chiudi del tutto RT alla chiusura?"
        confirmLabel="Chiudi del tutto"
        onCancel={() => setConfirmQuit(false)}
        onConfirm={() => {
          setConfirmQuit(false)
          save.mutate({ chiusura_x: 'esci' })
        }}
      >
        <p>Ogni volta che chiudi la finestra con la X, RT smetterà di lavorare in background e i job in corso si fermeranno.</p>
      </ConfirmDialog>
    </SettingsGroup>
  )
}
