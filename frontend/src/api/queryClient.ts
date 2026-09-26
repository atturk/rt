import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from './client'

/**
 * Nessuno stato di dominio nel frontend: i dati vivono nella cache di TanStack Query, che
 * rilegge dall'API; dopo ogni scrittura le mutation invalidano le query interessate.
 * Un 401 ovunque riporta alla pagina di accesso.
 */
export function createQueryClient(onUnauthorized: () => void): QueryClient {
  const handle = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onUnauthorized()
  }
  return new QueryClient({
    queryCache: new QueryCache({ onError: handle }),
    mutationCache: new MutationCache({ onError: handle }),
    defaultOptions: {
      queries: {
        retry: (count, error) => !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
        refetchOnWindowFocus: true,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  })
}
