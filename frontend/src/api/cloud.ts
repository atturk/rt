import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { settingsKeys } from './settings'

/** Modalità facilitata (RT Cloud): accesso con codice email, abbonamento e saldo. */

export type CloudStatus = Schemas['CloudStatus']

export const cloudKeys = { status: ['cloud'] as const }

export function useCloudStatus() {
  return useQuery({ queryKey: cloudKeys.status, queryFn: () => unwrap(api.GET('/api/v1/cloud')), staleTime: 60_000 })
}

/** Le operazioni che cambiano account o chiave rileggono stato e impostazioni (connessioni, fasi). */
function useCloudMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async (data) => {
      if (data && typeof data === 'object' && 'logged_in' in data) client.setQueryData(cloudKeys.status, data)
      await client.invalidateQueries({ queryKey: settingsKeys.all })
    },
  })
}

export function useCloudLoginStart() {
  return useMutation({ mutationFn: (email: string) => unwrap(api.POST('/api/v1/cloud/login/start', { body: { email } })) })
}

export function useCloudLoginVerify() {
  return useCloudMutation((body: { email: string; code: string }) => unwrap(api.POST('/api/v1/cloud/login/verify', { body })))
}

/** assign_all: porta tutte le fasi testuali su RT Cloud (scelta esplicita della modalità facilitata). */
export function useCloudSync() {
  return useCloudMutation((assign_all: boolean) => unwrap(api.POST('/api/v1/cloud/sync', { body: { assign_all } })))
}

export function useCloudLogout() {
  return useCloudMutation(() => unwrap(api.POST('/api/v1/cloud/logout')))
}

export function useCloudCheckout() {
  return useMutation({ mutationFn: (plan?: string) => unwrap(api.POST('/api/v1/cloud/checkout', { body: { plan: plan ?? null } })) })
}

export function useCloudPortal() {
  return useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/cloud/portal')) })
}
