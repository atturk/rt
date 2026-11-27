import { useState, type FormEvent, type ReactNode } from 'react'

import { useSaveTranscription, type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SecretInput } from '@/components/ui/secret-input'
import { isAppWindow } from '@/lib/zoom'
import { ExtraSecretDelete } from './keys'
import { AutoSaveStatus, SaveFeedback, SecretBadge, SettingsGroup, SettingsInfoButton, SettingsRow, SettingsSelect as Select, SettingsSwitch } from './ui'
import { useAutoSave } from './useAutoSave'
import { useGeneralPreference } from './useGeneralPreference'

export function TranscriptionSection({ settings }: { settings: Settings }) {
  const save = useSaveTranscription()
  return <TranscriptionFields settings={settings} save={save} />
}

type Engine = 'macparakeet' | 'parakeet' | 'custom'

const ENGINE_LABEL: Record<Engine, string> = {
  parakeet: 'Parakeet ONNX',
  macparakeet: 'macparakeet (avanzato)',
  custom: 'Server OpenAI-compatible',
}

function engineHint(t: Settings['transcription'], engine: Engine): ReactNode {
  if (engine === 'macparakeet') {
    if (!t.macparakeet_available) return 'macparakeet funziona solo su macOS: scegli Parakeet ONNX.'
    if (t.macparakeet_installed) return 'Scelta avanzata (installato con Homebrew): usa il Neural Engine del Mac.'
    if (t.macparakeet_fallback || t.parakeet_available) {
      return 'Scelta avanzata (se installato con Homebrew). Non è installato su questo Mac: RT usa Parakeet ONNX.'
    }
    return 'Scelta avanzata (se installato con Homebrew): non trovato su questo Mac.'
  }
  if (engine === 'parakeet') {
    if (!t.parakeet_available) return 'Il motore non è installato: reinstalla RT.'
    return t.parakeet_model_ready
      ? 'Gira su questo computer, senza internet.'
      : 'Gira su questo computer. Il modello (~670 MB) si scarica qui sotto in «Componenti di RT» oppure alla prima trascrizione.'
  }
  return 'Un tuo server di trascrizione, con risposta verbose_json e segmenti temporizzati.'
}

function TranscriptionFields({
  settings,
  save,
}: {
  settings: Settings
  save: ReturnType<typeof useSaveTranscription>
}) {
  const t = settings.transcription
  const savedEngine = t.engine as Engine
  const savedUrl = t.base_url ?? ''
  const savedModel = t.model ?? ''

  const [engineDraft, setEngineDraft] = useState<{ base: Engine; value: Engine } | null>(null)
  const [urlDraft, setUrlDraft] = useState<{ base: string; value: string } | null>(null)
  const [modelDraft, setModelDraft] = useState<{ base: string; value: string } | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [keyStatus, setKeyStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [keyError, setKeyError] = useState<string | null>(null)
  const [engineStatus, setEngineStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [engineError, setEngineError] = useState<string | null>(null)

  const engine = engineDraft && engineDraft.base === savedEngine ? engineDraft.value : savedEngine
  const baseUrl = urlDraft && urlDraft.base === savedUrl ? urlDraft.value : savedUrl
  const model = modelDraft && modelDraft.base === savedModel ? modelDraft.value : savedModel

  const custom = engine === 'custom'
  const engines: Engine[] = t.macparakeet_available || t.engine === 'macparakeet' ? ['parakeet', 'macparakeet', 'custom'] : ['parakeet', 'custom']

  const urlAuto = useAutoSave(
    save,
    baseUrl,
    {
      delay: 600,
      enabled: custom,
      initial: savedUrl,
      equals: (a, b) => a.trim() === b.trim(),
      serialize: (val) => ({ engine, base_url: val.trim(), model: model.trim(), api_key: null }),
    },
  )

  const modelAuto = useAutoSave(
    save,
    model,
    {
      delay: 600,
      enabled: custom,
      initial: savedModel,
      equals: (a, b) => a.trim() === b.trim(),
      serialize: (val) => ({ engine, base_url: baseUrl.trim(), model: val.trim(), api_key: null }),
    },
  )

  function handleEngineChange(next: Engine) {
    setEngineDraft({ base: savedEngine, value: next })
    setEngineStatus('saving')
    setEngineError(null)
    save.mutate(
      { engine: next, base_url: baseUrl.trim(), model: model.trim(), api_key: null },
      {
        onSuccess: () => {
          setEngineStatus('saved')
          setTimeout(() => setEngineStatus((s) => (s === 'saved' ? 'idle' : s)), 1500)
        },
        onError: (err) => {
          setEngineStatus('error')
          setEngineError(err instanceof Error ? err.message : 'Errore durante il salvataggio.')
        },
      },
    )
  }

  function submitKey(e: FormEvent) {
    e.preventDefault()
    if (!apiKey.trim()) return
    setKeyStatus('saving')
    setKeyError(null)
    save.mutate(
      { engine, base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() },
      {
        onSuccess: () => {
          setApiKey('')
          setKeyStatus('saved')
          setTimeout(() => setKeyStatus((s) => (s === 'saved' ? 'idle' : s)), 1500)
        },
        onError: (err) => {
          setKeyStatus('error')
          setKeyError(err instanceof Error ? err.message : 'Errore durante il salvataggio.')
        },
      },
    )
  }

  return (
    <SettingsGroup
      id="trascrizione"
      title="Trascrizione"
      description="Motore usato per trascrivere l'audio delle lezioni e le risposte vocali."
    >
      <SettingsRow
        label="Motore"
        htmlFor="stt-engine"
        description={<span data-testid="stt-engine-hint">{engineHint(t, engine)}</span>}
        status={{
          status: engineStatus,
          error: engineError,
          retry: () => handleEngineChange(engine),
        }}
        control={
          <Select id="stt-engine" className="w-full @sm:w-64" value={engine} onChange={(e) => handleEngineChange(e.target.value as Engine)}>
            {engines.map((name) => (
              <option key={name} value={name}>
                {ENGINE_LABEL[name]}
                {name === t.recommended ? ' · consigliato' : ''}
              </option>
            ))}
          </Select>
        }
      />
      {custom && (
        <>
          <SettingsRow
            label="Base URL del server"
            htmlFor="stt-base-url"
            status={urlAuto}
            control={
              <Input
                id="stt-base-url"
                className="w-full @sm:w-60"
                value={baseUrl}
                onChange={(e) => setUrlDraft({ base: savedUrl, value: e.target.value })}
                onBlur={urlAuto.flush}
                placeholder="http://localhost:8000/v1"
              />
            }
          />
          <SettingsRow
            label="Modello"
            htmlFor="stt-model"
            status={modelAuto}
            control={
              <Input
                id="stt-model"
                className="w-full @sm:w-60"
                value={model}
                onChange={(e) => setModelDraft({ base: savedModel, value: e.target.value })}
                onBlur={modelAuto.flush}
                placeholder="whisper-1"
              />
            }
          />
          <SettingsRow
            label="Chiave API (facoltativa)"
            htmlFor="stt-key"
            description={
              <span className="inline-flex flex-wrap items-center gap-2">
                <span>Chiave:</span>
                <SecretBadge set={t.api_key_set} />
                <ExtraSecretDelete name="RT_STT_API_KEY" label="chiave STT" set={t.api_key_set} />
              </span>
            }
            control={
              <form onSubmit={submitKey} className="flex w-full flex-col gap-1.5 @sm:w-auto @sm:items-end">
                <div className="flex w-full items-center gap-2 @sm:w-80">
                  <SecretInput
                    id="stt-key"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t.api_key_set ? 'Lascia vuoto per mantenere quella salvata' : ''}
                  />
                  <Button type="submit" size="sm" variant="outline" disabled={!apiKey.trim() || keyStatus === 'saving'}>
                    Salva chiave
                  </Button>
                </div>
                <AutoSaveStatus status={keyStatus} error={keyError} />
              </form>
            }
          />
        </>
      )}
    </SettingsGroup>
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

export function StartAtLoginSection({ settings }: { settings: Settings }) {
  const save = useGeneralPreference()
  const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform || navigator.userAgent)
  if (!isAppWindow() || !isMac) return null
  const enabled = settings.preferences?.avvia_all_accesso ?? true

  return (
    <SettingsGroup id="avvio-accesso" title="Avvio all'accesso">
      <SettingsSwitch
        id="pref-start-at-login"
        label="Avvia RT all'accesso"
        description="Avvia RT all'accesso: le elaborazioni ripartono da sole dopo il riavvio del Mac."
        checked={enabled}
        disabled={save.isPending}
        onChange={(checked) => save.mutate({ avvia_all_accesso: checked })}
      />
      {save.isError && (
        <div className="px-4 py-3">
          <SaveFeedback mutation={save} />
        </div>
      )}
    </SettingsGroup>
  )
}
