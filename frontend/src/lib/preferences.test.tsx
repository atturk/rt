import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { migrateLegacyPreferences, PREFERENCES_KEY, usePreference } from './preferences'
import { useTheme } from './theme'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
function client() { return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }) }
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('migra tema e audio una volta e non sostituisce una copia nuova', () => {
  localStorage.setItem('rt-theme', 'dark')
  localStorage.setItem('rt-playback-rate', '1.25')
  expect(migrateLegacyPreferences()).toEqual({ theme: 'scuro', 'audio.rate': 1.25 })
  expect(localStorage.getItem('rt-theme')).toBeNull()
  expect(localStorage.getItem('rt-playback-rate')).toBeNull()
  localStorage.setItem('rt-theme', 'light')
  expect(migrateLegacyPreferences().theme).toBe('scuro')
  expect(JSON.parse(localStorage.getItem('rt-pref:theme')!)).toBe('scuro')
})

it('mostra subito la copia locale, poi quella di RT, senza importare sopra RT', async () => {
  localStorage.setItem('rt-theme', 'dark')
  let resolve!: (value: never) => void
  vi.spyOn(api, 'GET').mockReturnValue(new Promise(r => { resolve = r }))
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(undefined))
  const hook = renderHook(() => usePreference('theme', 'sistema'), { wrapper: wrapper(client()) })
  expect(hook.result.current[0]).toBe('scuro')
  await act(async () => resolve(ok({ theme: 'chiaro' })))
  await waitFor(() => expect(hook.result.current[0]).toBe('chiaro'))
  expect(put).not.toHaveBeenCalled()
  expect(localStorage.getItem('rt-pref:migrations')).toBeNull()
})

it('importa su RT le vecchie preferenze solo quando assenti', async () => {
  localStorage.setItem('rt-playback-rate', '1.5')
  vi.spyOn(api, 'GET').mockResolvedValue(ok({}))
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(undefined))
  const hook = renderHook(() => usePreference('audio.rate', 1), { wrapper: wrapper(client()) })
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'audio.rate' } }, body: 1.5 }))
  await waitFor(() => expect(hook.result.current[0]).toBe(1.5))
})

it('condivide l’aggiornamento ottimistico e annulla l’errore senza perdere altre preferenze', async () => {
  const queryClient = client()
  queryClient.setQueryData(PREFERENCES_KEY, { theme: 'chiaro', altra: 3 })
  vi.spyOn(api, 'GET').mockResolvedValue(ok({ theme: 'chiaro', altra: 3 }))
  let reject!: (error: Error) => void
  vi.spyOn(api, 'PUT').mockReturnValue(new Promise((_resolve, r) => { reject = r }))
  const hook = renderHook(() => [usePreference('theme', 'sistema'), usePreference('theme', 'sistema')], { wrapper: wrapper(queryClient) })
  act(() => hook.result.current[0][1]('scuro'))
  await waitFor(() => expect(hook.result.current[1][0]).toBe('scuro'))
  expect(JSON.parse(localStorage.getItem('rt-pref:theme')!)).toBe('scuro')
  await act(async () => reject(new Error('offline')))
  await waitFor(() => expect(hook.result.current[0][0]).toBe('chiaro'))
  expect(queryClient.getQueryData(PREFERENCES_KEY)).toEqual({ theme: 'chiaro', altra: 3 })
})

it('DELETE toglie la copia locale e restituisce il predefinito', async () => {
  const queryClient = client()
  queryClient.setQueryData(PREFERENCES_KEY, { theme: 'chiaro' })
  vi.spyOn(api, 'GET').mockResolvedValue(ok({}))
  const deletion = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(undefined))
  const hook = renderHook(() => usePreference('theme', 'sistema'), { wrapper: wrapper(queryClient) })
  act(() => hook.result.current[1](undefined))
  await waitFor(() => expect(deletion).toHaveBeenCalled())
  await waitFor(() => expect(hook.result.current[0]).toBe('sistema'))
  expect(localStorage.getItem('rt-pref:theme')).toBeNull()
})

it('Sistema reagisce al cambio del dispositivo; un tema esplicito resta fisso', async () => {
  let dark = false
  let listener!: () => void
  vi.stubGlobal('matchMedia', () => ({ get matches() { return dark }, addEventListener: (_: string, fn: () => void) => { listener = fn }, removeEventListener: vi.fn() }))
  const queryClient = client()
  queryClient.setQueryData(PREFERENCES_KEY, { theme: 'sistema' })
  renderHook(useTheme, { wrapper: wrapper(queryClient) })
  expect(document.documentElement).not.toHaveClass('dark')
  act(() => { dark = true; listener() })
  expect(document.documentElement).toHaveClass('dark')
  act(() => queryClient.setQueryData(PREFERENCES_KEY, { theme: 'chiaro' }))
  await waitFor(() => expect(document.documentElement).not.toHaveClass('dark'))
})
