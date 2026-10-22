import { useState, type FormEvent } from 'react'

import { useSaveTranscription, useSaveWorker, type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { SettingsSelect as Select } from './common'
import { Field, SaveFeedback, SecretBadge, Section } from './common'

import { ExtraSecretDelete } from './keys'

/** I form sono inizializzati dai valori salvati e rimontati (key) quando il backend cambia:
 * dopo ogni salvataggio si vede quello che l'API ha scritto, non quello che si era digitato. */

const WORKER_CONCURRENCY_OPTIONS = [1, 2, 3, 4]

/** "Job in parallelo": quanti job il worker avviato con la web esegue insieme (vale dal prossimo avvio). */
export function WorkerSection({ settings }: { settings: Settings }) {
  const save = useSaveWorker()
  const saved = (settings.worker as { concurrency?: number; running: number }).concurrency ?? 8
  const running = settings.worker.running
  return (
    <Section id="job-paralleli" title="Job">
      <WorkerFields key={saved} saved={saved} pending={save.isPending} onSubmit={(n) => save.mutate(n)} />
      <p className="text-meta text-muted-foreground">
        Vale dal prossimo avvio di RT.
        {running > 0 && running !== saved && ` Ora ne esegue fino a ${running} insieme.`}
      </p>
      <SaveFeedback mutation={save} success="Salvato: vale dal prossimo avvio di RT." />
    </Section>
  )
}

function WorkerFields({ saved, pending, onSubmit }: { saved: number; pending: boolean; onSubmit: (n: number) => void }) {
  const [value, setValue] = useState(saved)
  return (
    <form
      className="flex flex-wrap items-center gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(value)
      }}
    >
      <label htmlFor="worker-concurrency" className="text-body font-medium">
        Job in parallelo
      </label>
      <Select aria-label="Job in parallelo" id="worker-concurrency" className="w-20" value={value} onChange={(e) => setValue(Number(e.target.value))}>
        {WORKER_CONCURRENCY_OPTIONS.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </Select>
      <Button type="submit" variant="outline" size="sm" disabled={pending || value === saved}>
        Salva
      </Button>
    </form>
  )
}

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
