import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { clampRate } from './playbackRate'

export const PREFERENCES_KEY = ['preferences'] as const
const PREFIX = 'rt-pref:'
const MIGRATIONS = 'rt-pref:migrations'
type Preferences = Record<string, unknown>

export function readPreference<T>(name: string, fallback: T): T {
  if (name === 'theme' || name === 'audio.rate') migrateLegacyPreferences()
  try {
    const raw = localStorage.getItem(PREFIX + name)
    return raw === null ? fallback : JSON.parse(raw) as T
  } catch { return fallback }
}

function cachePreference(name: string, value: unknown) {
  try {
    if (value === undefined) localStorage.removeItem(PREFIX + name)
    else localStorage.setItem(PREFIX + name, JSON.stringify(value))
  } catch { /* La copia locale è facoltativa. */ }
}

/** Si importa solo se RT non ha già una preferenza: il dispositivo nuovo non la sovrascrive. */
export function migrateLegacyPreferences(): Preferences {
  try {
    const pending: Preferences = JSON.parse(localStorage.getItem(MIGRATIONS) ?? '{}')
    const theme = localStorage.getItem('rt-theme')
    const rate = localStorage.getItem('rt-playback-rate')
    if (theme !== null && localStorage.getItem(PREFIX + 'theme') === null) {
      pending.theme = theme === 'dark' ? 'scuro' : theme === 'light' ? 'chiaro' : 'sistema'
      cachePreference('theme', pending.theme)
    }
    if (rate !== null && localStorage.getItem(PREFIX + 'audio.rate') === null) {
      pending['audio.rate'] = clampRate(Number(rate))
      cachePreference('audio.rate', pending['audio.rate'])
    }
    localStorage.setItem(MIGRATIONS, JSON.stringify(pending))
    localStorage.removeItem('rt-theme')
    localStorage.removeItem('rt-playback-rate')
    return pending
  } catch { return {} }
}

async function fetchPreferences(): Promise<Preferences> {
  const pending = migrateLegacyPreferences()
  const values = await unwrap(api.GET('/api/v1/preferences'))
  for (const [name, value] of Object.entries(pending)) {
    if (!Object.hasOwn(values, name)) {
      await unwrap(api.PUT('/api/v1/preferences/{name}', { params: { path: { name } }, body: value }))
      values[name] = value
    }
  }
  try { localStorage.removeItem(MIGRATIONS) } catch { /* Copia facoltativa. */ }
  return values
}

/** Il primo valore viene dalla copia locale; RT resta la fonte condivisa e autorevole. */
export function usePreference<T>(name: string, fallback: T): [T, (value: T | undefined) => void] {
  const client = useQueryClient()
  const query = useQuery({ queryKey: PREFERENCES_KEY, queryFn: fetchPreferences, staleTime: 30_000 })
  const mutation = useMutation({
    mutationKey: [...PREFERENCES_KEY, name],
    scope: { id: `preference:${name}` },
    mutationFn: (value: T | undefined) => value === undefined
      ? unwrap(api.DELETE('/api/v1/preferences/{name}', { params: { path: { name } } }))
      : unwrap(api.PUT('/api/v1/preferences/{name}', { params: { path: { name } }, body: value })),
    onMutate: async (value) => {
      await client.cancelQueries({ queryKey: PREFERENCES_KEY })
      const previous = client.getQueryData<Preferences>(PREFERENCES_KEY)?.[name]
      client.setQueryData<Preferences>(PREFERENCES_KEY, old => {
        const next = { ...old }
        if (value === undefined) delete next[name]
        else next[name] = value
        return next
      })
      cachePreference(name, value)
      return { previous }
    },
    onError: (_error, _value, context) => {
      client.setQueryData<Preferences>(PREFERENCES_KEY, old => {
        const next = { ...old }
        if (context?.previous === undefined) delete next[name]
        else next[name] = context.previous
        return next
      })
      cachePreference(name, context?.previous)
    },
    onSettled: () => {
      if (client.isMutating({ mutationKey: PREFERENCES_KEY }) === 1)
        void client.invalidateQueries({ queryKey: PREFERENCES_KEY })
    },
  })
  useEffect(() => {
    if (query.data !== undefined) cachePreference(name, query.data[name])
  }, [name, query.data])
  const value = query.data === undefined ? readPreference(name, fallback)
    : Object.hasOwn(query.data, name) ? query.data[name] as T : fallback
  return [value, mutation.mutate]
}
