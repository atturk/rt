import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { useListenTopics, useSaveLessonsRoot, useSaveTelegram, useSaveTranscription, useTopicTest, type Settings } from '@/api/settings'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { matchesPreview, mergeListenedTopics, parseTopicLink, rowsToTopicNames, rowsToTopics, topicsToRows, type TopicRow } from '@/lib/settings'
import { Field, SaveFeedback, SecretBadge, Section } from './common'
import { FolderField } from './folders'
import { ListenCleanup, RevealableValue, TopicTestButton, TopicTestResult } from './telegram'

/** I form sono inizializzati dai valori salvati e rimontati (key) quando il backend cambia:
 * dopo ogni salvataggio si vede quello che l'API ha scritto, non quello che si era digitato. */

export function LessonsRootForm({ settings, onSaved, submitLabel = 'Salva' }: { settings: Settings; onSaved?: () => void; submitLabel?: string }) {
  const save = useSaveLessonsRoot()
  return (
    <>
      <LessonsRootFields
        key={settings.lessons_root ?? ''}
        initial={settings.lessons_root ?? '~/RT Lezioni'}
        pending={save.isPending}
        submitLabel={submitLabel}
        onSubmit={(path) => save.mutate(path, { onSuccess: onSaved })}
      />
      <SaveFeedback mutation={save} />
    </>
  )
}

function LessonsRootFields({ initial, pending, submitLabel, onSubmit }: { initial: string; pending: boolean; submitLabel: string; onSubmit: (path: string) => void }) {
  const [path, setPath] = useState(initial)
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(path.trim())
      }}
    >
      <FolderField id="lessons-root" value={path} onChange={setPath} />
      <div>
        <Button type="submit" disabled={pending || !path.trim()}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

export function LessonsRootSection({ settings }: { settings: Settings }) {
  return (
    <Section
      id="cartella"
      title="Cartella dati"
      description="Cartella che RT, il bot Telegram e il database usano per le lezioni."
    >
      <LessonsRootForm settings={settings} />
      {settings.data_dir && (
        <p className="text-xs text-muted-foreground">
          Database e media in uso: <code className="rounded bg-muted px-1" data-testid="data-dir">{settings.data_dir}</code>. Se cambi
          cartella, RT userà il database della nuova cartella dal prossimo avvio.
        </p>
      )}
    </Section>
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

function TranscriptionFields({
  settings,
  pending,
  onSubmit,
}: {
  settings: Settings
  pending: boolean
  onSubmit: (body: { engine: 'macparakeet' | 'custom'; base_url: string; model: string; api_key: string | null }) => void
}) {
  const t = settings.transcription
  const [engine, setEngine] = useState<'macparakeet' | 'custom'>(t.engine === 'custom' ? 'custom' : 'macparakeet')
  const [baseUrl, setBaseUrl] = useState(t.base_url ?? '')
  const [model, setModel] = useState(t.model ?? '')
  const [apiKey, setApiKey] = useState('')
  const custom = engine === 'custom'
  function submit(e: FormEvent) {
    e.preventDefault()
    onSubmit({ engine, base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() || null })
  }
  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={submit}>
      <Field label="Motore" htmlFor="stt-engine">
        <Select id="stt-engine" value={engine} onChange={(e) => setEngine(e.target.value as 'macparakeet' | 'custom')}>
          <option value="macparakeet">macparakeet (su questo Mac)</option>
          <option value="custom">Server OpenAI-compatible</option>
        </Select>
      </Field>
      <Field label="Base URL del server" htmlFor="stt-base-url">
        <Input id="stt-base-url" value={baseUrl} disabled={!custom} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:8000/v1" />
      </Field>
      <Field label="Modello" htmlFor="stt-model">
        <Input id="stt-model" value={model} disabled={!custom} onChange={(e) => setModel(e.target.value)} placeholder="whisper-1" />
      </Field>
      <Field label="Chiave API (facoltativa)" htmlFor="stt-key" hint={<>Chiave: <SecretBadge set={t.api_key_set} /></>}>
        <Input
          id="stt-key"
          type="password"
          autoComplete="off"
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

export function TelegramSection({ settings }: { settings: Settings }) {
  const save = useSaveTelegram()
  const [formError, setFormError] = useState<string | null>(null)
  const tg = settings.telegram
  return (
    <Section
      id="telegram"
      title="Telegram"
      description="Aggiungi il bot al gruppo e assegna un topic a ogni materia. Per trovare un topic, copia il link di un suo messaggio."
    >
      <TelegramFields
        key={JSON.stringify(tg)}
        settings={settings}
        pending={save.isPending}
        onError={setFormError}
        onSubmit={(body) => {
          setFormError(null)
          save.mutate(body)
        }}
      />
      {formError && <Alert tone="danger">{formError}</Alert>}
      <SaveFeedback mutation={save} />
    </Section>
  )
}

function TelegramFields({
  settings,
  pending,
  onSubmit,
  onError,
}: {
  settings: Settings
  pending: boolean
  onSubmit: (body: {
    bot_token: string | null
    chat_id: string | null
    topics: Record<string, number>
    misc_topic_id: number | null
    topic_names: Record<string, string>
  }) => void
  onError: (message: string | null) => void
}) {
  const tg = settings.telegram
  const [token, setToken] = useState('')
  // Il Chat ID salvato non arriva nella risposta delle impostazioni (solo l'anteprima): il
  // campo resta vuoto e, se non lo si cambia, il backend mantiene quello salvato.
  const [chatId, setChatId] = useState('')
  const [rows, setRows] = useState<TopicRow[]>(() => {
    const saved = topicsToRows(tg.topics, tg.topic_names)
    return saved.length ? saved : [{ materia: '', topic: '' }]
  })
  const [misc, setMisc] = useState(tg.misc_topic_id == null ? '' : String(tg.misc_topic_id))
  const [link, setLink] = useState('')

  function update(index: number, patch: Partial<TopicRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  // Ascolto dei topic: a job concluso aggiunge al form chat e topic rilevati (da salvare).
  const listen = useListenTopics()
  function startListening() {
    listen.mutate(undefined, {
      onSuccess: (result) => {
        if (!result.ok) return
        const detected = result.chat_id
        // Come prima dell'anteprima: il Chat ID rilevato riempie il campo solo se non ce n'è uno salvato.
        if (detected && !tg.chat_id_set) setChatId((current) => current.trim() || detected)
        setRows((current) => mergeListenedTopics(current, result))
      },
    })
  }

  function addFromLink() {
    const parsed = parseTopicLink(link)
    if (!parsed) return onError('Incolla un link a un messaggio del topic, per esempio https://t.me/c/1234567890/12/34.')
    const configured = chatId.trim() ? chatId.trim() === parsed.chatId : matchesPreview(parsed.chatId, tg.chat_id_preview)
    if (!configured) return onError('Questo topic appartiene a un gruppo diverso dal Chat ID configurato.')
    onError(null)
    setChatId(parsed.chatId)
    if (!rows.some((r) => r.topic.trim() === String(parsed.topicId))) {
      setRows((current) => [...current.filter((r) => r.materia.trim() || r.topic.trim()), { materia: '', topic: String(parsed.topicId) }])
    }
    setLink('')
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    let topics: Record<string, number>
    try {
      topics = rowsToTopics(rows)
    } catch (err) {
      return onError((err as Error).message)
    }
    if (misc.trim() && !/^\d+$/.test(misc.trim())) return onError('Il topic generale deve essere un numero.')
    onSubmit({
      bot_token: token.trim() || null,
      chat_id: chatId.trim() || null,
      topics,
      misc_topic_id: misc.trim() ? Number(misc.trim()) : null,
      topic_names: rowsToTopicNames(rows),
    })
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Token del bot" htmlFor="tg-token" hint={<>Token salvato: <RevealableValue field="bot_token" preview={tg.bot_token_preview} /></>}>
          <Input
            id="tg-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={tg.bot_token_set ? 'Lascia vuoto per mantenere quello salvato' : '123456:ABC…'}
          />
        </Field>
        <Field label="Chat ID del gruppo" htmlFor="tg-chat" hint={<>Chat ID salvato: <RevealableValue field="chat_id" preview={tg.chat_id_preview} /></>}>
          <Input
            id="tg-chat"
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder={tg.chat_id_set ? 'Lascia vuoto per mantenere quello salvato' : '-1001234567890'}
          />
        </Field>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-xs font-semibold text-muted-foreground">Topic per materia</legend>
        {rows.map((row, i) => (
          <TopicRowFields
            key={i}
            index={i}
            row={row}
            onChange={(patch) => update(i, patch)}
            onRemove={() => setRows((c) => c.filter((_, j) => j !== i))}
          />
        ))}
        <div>
          <Button variant="outline" size="sm" onClick={() => setRows((c) => [...c, { materia: '', topic: '' }])}>
            <Plus /> Aggiungi topic
          </Button>
        </div>
      </fieldset>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <Field label="Link a un messaggio del topic" htmlFor="tg-link">
          <Input id="tg-link" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://t.me/c/1234567890/12/34" />
        </Field>
        <Button variant="outline" onClick={addFromLink} disabled={!link.trim()}>
          Aggiungi dal link
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start gap-2">
          <Button variant="outline" onClick={startListening} disabled={!tg.bot_token_set || listen.isPending}>
            Ascolta i topic per 20 secondi
          </Button>
          <ListenCleanup enabled={tg.bot_token_set} />
        </div>
        <span className="text-[11px] text-muted-foreground">
          {tg.bot_token_set
            ? 'Poi scrivi un messaggio in ogni topic dal telefono. Finito, puoi cancellare dal gruppo i messaggi usati per il rilevamento.'
            : 'Salva prima il token del bot.'}
        </span>
        {listen.isPending && (
          <p role="status" className="text-xs text-muted-foreground">
            In ascolto…
          </p>
        )}
        {listen.isError && <Alert tone="danger">{errorMessage(listen.error)}</Alert>}
        {listen.data &&
          (listen.data.ok ? (
            <p role="status" className="text-xs text-success" data-testid="listen-result">
              {listen.data.message}
            </p>
          ) : (
            <Alert tone="danger" data-testid="listen-result">
              {listen.data.message}
            </Alert>
          ))}
      </div>

      <Field label="Topic generale (facoltativo)" htmlFor="tg-misc" hint="Per le lezioni di materie senza topic.">
        <Input id="tg-misc" value={misc} inputMode="numeric" onChange={(e) => setMisc(e.target.value)} className="sm:w-40" />
      </Field>
      <div>
        <Button type="submit" disabled={pending}>
          Salva Telegram
        </Button>
      </div>
    </form>
  )
}

/** Riga materia/topic con cestino e "Prova"; sotto il nome su Telegram e l'esito della prova. */
function TopicRowFields({ index, row, onChange, onRemove }: { index: number; row: TopicRow; onChange: (patch: Partial<TopicRow>) => void; onRemove: () => void }) {
  const test = useTopicTest(row.topic, row.materia || row.name || '')
  const n = index + 1
  return (
    <div className="flex flex-col gap-1" data-testid="topic-row">
      <div className="flex items-center gap-2">
        <Input aria-label={`Materia ${n}`} value={row.materia} placeholder="BIOCHIMICA" onChange={(e) => onChange({ materia: e.target.value })} />
        <Input aria-label={`Topic ${n}`} value={row.topic} inputMode="numeric" placeholder="12" className="w-28" onChange={(e) => onChange({ topic: e.target.value })} />
        <Button variant="ghost" size="icon" aria-label={`Rimuovi topic ${n}`} onClick={onRemove}>
          <Trash2 />
        </Button>
        <TopicTestButton state={test} label={`topic ${n}`} />
      </div>
      {row.name && (
        <p className="text-[11px] text-muted-foreground" data-testid="topic-name">
          Nome su Telegram: <strong>{row.name}</strong>
        </p>
      )}
      <TopicTestResult state={test} />
    </div>
  )
}
