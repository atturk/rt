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
