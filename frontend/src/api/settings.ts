import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'

/** Hook delle impostazioni (RT4-F5). Ogni scrittura invalida le query delle impostazioni:
 * la pagina mostra sempre quello che il backend ha salvato, mai lo stato del form. */

export type Settings = Schemas['Settings']
export type RouteOut = Schemas['RouteOut']

export const settingsKeys = {
  all: ['settings'] as const,
  route: (job: string, role: string) => ['settings', 'route', job, role] as const,
  job: (id: string) => ['job', id] as const,
}

export function useSettings() {
  // Letta anche da SetupGate a ogni pagina: le scritture la invalidano, quindi può restare in cache.
  return useQuery({ queryKey: settingsKeys.all, queryFn: () => unwrap(api.GET('/api/v1/settings')), staleTime: 30_000 })
}

/** Mutation che dopo il successo rilegge tutte le impostazioni (e le lezioni se serve). */
function useSettingsMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>, alsoLessons = false) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: settingsKeys.all })
      // Le lezioni si rileggono in background: la pagina non aspetta l'elenco per proseguire.
      if (alsoLessons) void client.invalidateQueries({ queryKey: ['lessons'] })
    },
  })
}

export function useSaveLessonsRoot() {
  return useSettingsMutation(
    (path: string) => unwrap(api.PUT('/api/v1/settings/lessons-root', { body: { path } })),
    true,
  )
}

export function useSaveTranscription() {
  return useSettingsMutation((body: Schemas['TranscriptionIn']) => unwrap(api.PUT('/api/v1/settings/transcription', { body })))
}

export function useSaveTelegram() {
  return useSettingsMutation((body: Schemas['TelegramIn']) => unwrap(api.PUT('/api/v1/settings/telegram', { body })))
}

export function useCreateConnection() {
  return useSettingsMutation((body: Schemas['ConnectionIn']) => unwrap(api.POST('/api/v1/settings/connections', { body })))
}

export function useAddModel() {
  return useSettingsMutation(({ connection, model }: { connection: string; model: string }) =>
    unwrap(api.POST('/api/v1/settings/connections/{name}/models', { params: { path: { name: connection } }, body: { model } })),
  )
}

export function useAssignPhase() {
  return useSettingsMutation(({ job, connection, model }: { job: string; connection: string; model: string }) =>
    unwrap(api.PUT('/api/v1/settings/phases/{job}', { params: { path: { job } }, body: { connection, model } })),
  )
}

/** Stesso modello per tutte le fasi (configurazione guidata): una rilettura sola alla fine. */
export function useAssignAllPhases() {
  return useSettingsMutation(async ({ jobs, connection, model }: { jobs: string[]; connection: string; model: string }) => {
    for (const job of jobs) {
      await unwrap(api.PUT('/api/v1/settings/phases/{job}', { params: { path: { job } }, body: { connection, model } }))
    }
  })
}

export function useSavePricing() {
  return useSettingsMutation((body: Settings['pricing']) => unwrap(api.PUT('/api/v1/settings/pricing', { body })))
}

export function useSaveSecret() {
  return useSettingsMutation(({ name, value }: { name: string; value: string }) =>
    unwrap(api.PUT('/api/v1/secrets/{name}', { params: { path: { name } }, body: { value } })),
  )
}

export function useRoute(job: string, role: string) {
  return useQuery({
    queryKey: settingsKeys.route(job, role),
    queryFn: () => unwrap(api.GET('/api/v1/settings/routes/{job}/{role}', { params: { path: { job, role } } })),
    enabled: !!job && !!role,
  })
}

export function useSaveRoute() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ job, role, body }: { job: string; role: string; body: Schemas['RouteIn'] }) =>
      unwrap(api.PUT('/api/v1/settings/routes/{job}/{role}', { params: { path: { job, role } }, body })),
    // La route primaria è anche l'assegnazione della fase: rileggi tutto.
    onSuccess: () => client.invalidateQueries({ queryKey: settingsKeys.all }),
  })
}

/** Prova di una credenziale: accoda il job credential_test; l'esito si legge da useJob. */
export function useTestCredential() {
  return useMutation({
    mutationFn: (body: Schemas['CredentialTest']) => unwrap(api.POST('/api/v1/settings/test-credential', { body })),
  })
}

/** "Ascolta i topic": job che legge per 20 secondi i messaggi arrivati al bot. Con names
 * (nome del topic dal Bot API) e materie (materia nota che coincide con il nome). */
export type ListenResult = {
  ok: boolean
  message: string
  chat_id?: string | null
  topics?: number[]
  names?: Record<string, string>
  materie?: Record<string, string>
}

export const telegramSettingsKeys = { listenMessages: ['settings', 'telegram', 'listen-messages'] as const }

export function useListenTopics() {
  const client = useQueryClient()
  return useMutation({
    onSettled: () => client.invalidateQueries({ queryKey: telegramSettingsKeys.listenMessages }),
    mutationFn: async (): Promise<ListenResult> => {
      const accepted = await unwrap(api.POST('/api/v1/settings/telegram/listen-topics'))
      if (!accepted.worker_available) return { ok: false, message: 'Nessun worker attivo: avvia rt worker e riprova.' }
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        const job = await unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: accepted.job_id } } }))
        if (job.state === 'succeeded') return job.result as ListenResult
        if (isTerminal(job.state)) return { ok: false, message: `Ascolto non eseguito: ${job.error ?? job.state}` }
      }
    },
  })
}

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

export function isTerminal(state: string | undefined) {
  return !!state && TERMINAL.has(state)
}

/** Stato di un job, riletto ogni secondo finché non finisce. */
export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: settingsKeys.job(id ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id! } } })),
    enabled: !!id,
    refetchInterval: (query) => (isTerminal(query.state.data?.state) ? false : 1000),
  })
}

/** Messaggi ricevuti durante l'ultimo ascolto dei topic (quanti e se già cancellati). */
export function useListenMessages(enabled = true) {
  return useQuery({
    queryKey: telegramSettingsKeys.listenMessages,
    queryFn: () => unwrap(api.GET('/api/v1/settings/telegram/listen-messages')),
    enabled,
  })
}

/** Cancella dal gruppo solo i messaggi dell'ultimo ascolto. */
export function useDeleteListenMessages() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/listen-messages/delete')),
    onSettled: () => client.invalidateQueries({ queryKey: telegramSettingsKeys.listenMessages }),
  })
}

/** Valore completo del token del bot o del Chat ID: solo su richiesta esplicita (pulsante occhio). */
export function useRevealTelegram() {
  return useMutation({
    mutationFn: (field: 'bot_token' | 'chat_id') => unwrap(api.POST('/api/v1/settings/telegram/reveal', { body: { field } })),
  })
}

/** "Prova": messaggio "Questo è il topic di <materia>" nel topic; l'esito è la risposta. */
export function useTestTopic() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['TopicTestIn']) => unwrap(api.POST('/api/v1/settings/telegram/test-topic', { body })),
    onSettled: () => client.invalidateQueries({ queryKey: ['telegram', 'notifications'] }),
  })
}

/** "Prova" di un topic dal form o dalla pagina Bot: la mutation e se l'id è valido. */
export function useTopicTest(topicId: string, materia: string) {
  const test = useTestTopic()
  const valid = /^\d+$/.test(topicId.trim()) && Number(topicId) > 0
  return { test, valid, run: () => test.mutate({ topic_id: Number(topicId.trim()), materia: materia.trim() }) }
}

/** Finestra di Finder (macOS) per scegliere una cartella; 'unavailable' altrove. */
export function useChooseFolder() {
  return useMutation({
    mutationFn: (start: string | null) => unwrap(api.POST('/api/v1/system/choose-folder', { body: { start } })),
  })
}

/** Sottocartelle di una cartella della home, per il navigatore (ripiego della finestra nativa). */
export function useFolders(path: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['system', 'folders', path ?? ''],
    queryFn: () => unwrap(api.GET('/api/v1/system/folders', { params: { query: path ? { path } : {} } })),
    enabled,
  })
}
