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

/** Mutation che dopo il successo rilegge tutte le impostazioni. */
function useSettingsMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: settingsKeys.all })
    },
  })
}

export function useSavePreferences() {
  return useSettingsMutation((body: Schemas['PreferencesSettings']) =>
    unwrap(api.PUT('/api/v1/settings/preferences', { body })),
  )
}

export function useSaveTranscription() {
  return useSettingsMutation((body: Schemas['TranscriptionIn']) => unwrap(api.PUT('/api/v1/settings/transcription', { body })))
}

/** Notifiche Telegram accese o spente (spente di predefinito). */
export function useSetTelegramEnabled() {
  return useSettingsMutation((enabled: boolean) => unwrap(api.PUT('/api/v1/settings/telegram/enabled', { body: { enabled } })))
}

export function useSaveTelegram() {
  return useSettingsMutation((body: Schemas['TelegramIn']) => unwrap(api.PUT('/api/v1/settings/telegram', { body })))
}

/** "Collega la chat": trova la chat di chi ha scritto /start al bot e la salva (con il token, se dato). */
export function useFindTelegramChat() {
  return useSettingsMutation((body: Schemas['TelegramChatIn']) => unwrap(api.POST('/api/v1/settings/telegram/chat', { body })))
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

/** Elimina una chiave (archivio cifrato, .env e ambiente), come 'rt secrets unset'. */
export function useDeleteSecret() {
  return useSettingsMutation((name: string) => unwrap(api.DELETE('/api/v1/secrets/{name}', { params: { path: { name } } })))
}

/** Elimina una connessione con modelli e chiavi; 409 se una fase, una route o il classificatore la usa ancora. */
export function useDeleteConnection() {
  return useSettingsMutation((name: string) =>
    unwrap(api.DELETE('/api/v1/settings/connections/{name}', { params: { path: { name } } })),
  )
}

export function useSystemInfo() {
  return useQuery({ queryKey: ['system-info'], queryFn: () => unwrap(api.GET('/api/v1/system/info')) })
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

export function useSaveWebSearch() {
  return useSettingsMutation(
    (vars: { searxng_base_url?: string | null; contextual_verification?: boolean } | string) => {
      const body = typeof vars === 'string' ? { searxng_base_url: vars } : vars
      return unwrap(api.PUT('/api/v1/settings/web-search', { body: body as any }))
    },
  )
}

/** "Prova" di connessione e modello indicati nel form, anche prima di salvarli: chiamata minima
 * e sincrona. L'esito è solo una prova, non un'impostazione: non invalida nulla. */
export type ModelTestResult = Schemas['ModelTestOut']

export function useTestModel() {
  return useMutation({
    mutationFn: (body: { connection: string; model: string; vision?: boolean }) =>
      unwrap(api.POST('/api/v1/settings/models/test', { body: { ...body, vision: body.vision ?? false, mock: false } })),
  })
}

/** Ricerca immagini di prova su SearXNG con l'URL scritto nel form. */
export function useTestWebSearch() {
  return useMutation({
    mutationFn: (searxng_base_url: string) =>
      unwrap(api.POST('/api/v1/settings/web-search/test', { body: { searxng_base_url, mock: false } })),
  })
}

/** Prova di una credenziale: accoda il job credential_test; l'esito si legge da useJob. */
export function useTestCredential() {
  return useMutation({
    mutationFn: (body: Schemas['CredentialTest']) => unwrap(api.POST('/api/v1/settings/test-credential', { body })),
  })
}

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

export function isTerminal(state: string | undefined) {
  return !!state && TERMINAL.has(state)
}

/** Stato di un job, riletto a ogni suo evento dal canale live (liveUpdates.ts). */
export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: settingsKeys.job(id ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id! } } })),
    enabled: !!id,
  })
}

/** Valore completo del token del bot o del Chat ID: solo su richiesta esplicita (pulsante occhio). */
export function useRevealTelegram() {
  return useMutation({
    mutationFn: (field: 'bot_token' | 'chat_id') => unwrap(api.POST('/api/v1/settings/telegram/reveal', { body: { field } })),
  })
}

// ---------------------------------------------------------------- chiave sola lettura (AP1)

export interface ReadonlyKeyInfo {
  configured: boolean
  created_at?: string | null
  key_preview?: string | null
}

export interface ReadonlyKeyCreated {
  key: string
  created_at: string
  key_preview: string
}

export function useReadonlyKey() {
  return useQuery({
    queryKey: ['settings', 'readonly-key'],
    queryFn: () => unwrap((api as any).GET('/api/v1/settings/readonly-key')) as Promise<ReadonlyKeyInfo>,
  })
}

export function useCreateReadonlyKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap((api as any).POST('/api/v1/settings/readonly-key')) as Promise<ReadonlyKeyCreated>,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['settings', 'readonly-key'] })
    },
  })
}

export function useRevokeReadonlyKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap((api as any).DELETE('/api/v1/settings/readonly-key')),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['settings', 'readonly-key'] })
    },
  })
}


