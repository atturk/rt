import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { settingsKeys } from './settings'

export type ComponentStatus = Schemas['ComponentStatus']
export type ComponentId = ComponentStatus['id']

export const componentsKeys = {
  all: ['system', 'components'] as const,
}

export function useComponents(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: componentsKeys.all,
    queryFn: () => unwrap(api.GET('/api/v1/components')),
    enabled: options?.enabled ?? true,
    refetchInterval: (query) => {
      const items = query.state.data
      return Array.isArray(items) && items.some((c) => c.state === 'downloading') ? 1000 : false
    },
  })
}

function useComponentMutation(fn: (id: ComponentId) => Promise<ComponentStatus>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: componentsKeys.all }),
        client.invalidateQueries({ queryKey: settingsKeys.all }),
      ])
    },
  })
}

export function useDownloadComponent() {
  return useComponentMutation((component_id) =>
    unwrap(api.POST('/api/v1/components/{component_id}/download', { params: { path: { component_id } } })),
  )
}

export function useCancelComponent() {
  return useComponentMutation((component_id) =>
    unwrap(api.POST('/api/v1/components/{component_id}/cancel', { params: { path: { component_id } } })),
  )
}

export function useDeleteComponent() {
  return useComponentMutation((component_id) =>
    unwrap(api.DELETE('/api/v1/components/{component_id}', { params: { path: { component_id } } })),
  )
}
