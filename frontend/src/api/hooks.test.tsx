import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { api } from './client'
import { isActiveJob, useLessons } from './hooks'

afterEach(() => vi.restoreAllMocks())

describe('isActiveJob', () => {
  it('solo i job in coda o in esecuzione sono attivi', () => {
    expect(isActiveJob('queued')).toBe(true)
    expect(isActiveJob('running')).toBe(true)
    for (const state of ['waiting_for_decision', 'succeeded', 'failed', 'cancelled', '']) expect(isActiveJob(state)).toBe(false)
  })
})

describe('useLessons', () => {
  it('non manda all\'API i filtri vuoti', async () => {
    const get = vi.spyOn(api, 'GET').mockResolvedValue({ data: [], error: undefined, response: new Response('[]') } as never)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => useLessons({ materia: 'FISIOLOGIA', state: '', q: undefined }), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(get).toHaveBeenCalledWith('/api/v1/lessons', { params: { query: { materia: 'FISIOLOGIA' } } })
  })
})
