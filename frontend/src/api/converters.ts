import { QueryClient, QueryClientContext, useQuery } from '@tanstack/react-query'
import { useContext } from 'react'

import { api, unwrap, type Schemas } from './client'

export type ConvertersInfo = Schemas['ConvertersInfo']

export const convertersKeys = {
  all: ['system', 'converters'] as const,
}

const fallbackClient = new QueryClient({
  defaultOptions: { queries: { retry: false, gcTime: 0 } },
})

export const convertersApi = {
  get: (): Promise<ConvertersInfo> => unwrap(api.GET('/api/v1/system/converters')),
}

/** Interroga la disponibilità dei convertitori di slide una sola volta per sessione. */
export function useConverters() {
  const hasContext = Boolean(useContext(QueryClientContext))
  return useQuery(
    {
      queryKey: convertersKeys.all,
      queryFn: () => convertersApi.get(),
      staleTime: Infinity,
      gcTime: Infinity,
      retry: false,
      enabled: hasContext,
    },
    hasContext ? undefined : fallbackClient,
  )
}
