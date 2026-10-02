import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'
import { lessonKeys } from './hooks'

export type Element = Schemas['Element']
export type GenerateInput = Schemas['GenerateIn']
export type EnrichmentSettings = Schemas['EnrichmentConfig']
export const enrichmentKey = (id: number) => ['enrichment', id] as const

/** Gli elementi in generazione (job enrichment_*) li aggiorna il canale live (liveUpdates.ts). */
export function useEnrichment(id: number) {
  return useQuery({ queryKey: enrichmentKey(id), queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/enrichment', {
    params: { path: { lesson_id: id } },
  })) })
}

export function useEnrichmentActions(id: number) {
  const client = useQueryClient()
  const params = { path: { lesson_id: id } }
  const refresh = () => {
    void client.invalidateQueries({ queryKey: enrichmentKey(id) })
    void client.invalidateQueries({ queryKey: lessonKeys.all(id) })
  }
  const analyze = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/lessons/{lesson_id}/enrichment/analyze', { params, body: { mock: false } })), onSuccess: refresh })
  const generate = useMutation({ mutationFn: (body: Partial<GenerateInput>) => unwrap(api.POST('/api/v1/lessons/{lesson_id}/enrichment/generate', { params, body: { kind: 'visualization', title: 'Elemento grafico', description: 'Generazione manuale', prompt: '', mode: 'interactive', mock: false, ...body } })), onSuccess: refresh })
  const action = useMutation({ mutationFn: ({ element, action }: { element: string; action: 'dismiss' | 'restore' | 'delete' }) => unwrap(api.POST('/api/v1/lessons/{lesson_id}/enrichment/{element_id}/action', {
    params: { path: { ...params.path, element_id: element } }, body: { action },
  })), onSuccess: refresh })
  const edit = useMutation({ mutationFn: ({ id: element, ...body }: Schemas['ElementEdit'] & { id: string }) => unwrap(api.PUT('/api/v1/lessons/{lesson_id}/enrichment/{element_id}', {
    params: { path: { ...params.path, element_id: element } }, body,
  })), onSuccess: refresh })
  const cap = useMutation({ mutationFn: (body: Schemas['Cap']) => unwrap(api.PUT('/api/v1/lessons/{lesson_id}/enrichment/cap', { params, body })), onSuccess: refresh })
  return { analyze, generate, action, edit, cap, refresh }
}

export function useBatchEnrichment() {
  return useMutation({ mutationFn: (lesson_ids: number[]) => unwrap(api.POST('/api/v1/enrichment/analyze', { body: { lesson_ids, mock: false } })) })
}

export function useEnrichmentSettings() {
  return useQuery({ queryKey: ['enrichment-settings'], queryFn: () => unwrap(api.GET('/api/v1/settings/enrichment')) })
}

export function useSaveEnrichmentSettings() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: EnrichmentSettings) => unwrap(api.PUT('/api/v1/settings/enrichment', { body })),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['enrichment-settings'] }); void client.invalidateQueries({ queryKey: ['enrichment'] }) } })
}
