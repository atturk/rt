import { useCallback, useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'
import { usePreference } from '@/lib/preferences'

export type AppUpdate = Schemas['AppUpdate']
export type UpdateNotice = 'available' | 'ready' | 'error'
export const updateKey = ['system', 'update'] as const
const BUSY_PHASES = new Set(['downloading', 'verifying', 'installing'])

export const UPDATE_NOTICE_LABELS: Record<UpdateNotice, string> = {
  available: 'Aggiornamento disponibile',
  ready: 'Aggiornamento pronto',
  error: 'Aggiornamento non riuscito',
}

export function computeUpdateNotice(
  data: AppUpdate | undefined,
  seen: string | null | undefined,
): { notice: UpdateNotice | null; seenKey: string | null } {
  if (!data) return { notice: null, seenKey: null }
  const phase = data.progress?.phase
  if (phase && BUSY_PHASES.has(phase)) {
    return { notice: null, seenKey: null }
  }
  let notice: UpdateNotice | null = null
  let version: string | null | undefined = null
  if (phase === 'error') {
    notice = 'error'
    version = data.progress?.target || data.latest || data.current
  } else if (data.ready || phase === 'ready') {
    notice = 'ready'
    version = data.latest || data.progress?.target || data.current
  } else if (data.available && data.latest) {
    notice = 'available'
    version = data.latest
  }
  if (!notice || !version) {
    return { notice: null, seenKey: null }
  }
  const seenKey = `${version}:${notice}`
  if (seen === seenKey) {
    return { notice: null, seenKey }
  }
  return { notice, seenKey }
}

export function useAppUpdate() {
  const client = useQueryClient()
  const update = useQuery({
    queryKey: updateKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/update')),
    refetchInterval: (query) => (BUSY_PHASES.has(query.state.data?.progress?.phase ?? '') ? 3000 : false),
  })
  const refresh = useMutation({
    mutationFn: () => unwrap(api.GET('/api/v1/system/update', { params: { query: { refresh: true } } })),
    onSuccess: (data) => client.setQueryData(updateKey, data),
  })
  const download = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/system/update')),
    onSuccess: (data) => client.setQueryData(updateKey, data),
  })
  const install = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/system/update/install')),
    onSuccess: (data) => client.setQueryData(updateKey, data),
  })
  const setChannel = useMutation({
    mutationFn: (channel: 'stable' | 'beta') => unwrap(api.PUT('/api/v1/system/update/channel', { body: { channel } })),
    onSuccess: (data) => client.setQueryData(updateKey, data),
  })
  const data = update.data as AppUpdate | undefined
  const phase = data?.progress?.phase
  const percent = data?.progress?.total ? Math.min(100, Math.round((data.progress.downloaded * 100) / data.progress.total)) : null

  return {
    update,
    data,
    phase,
    percent,
    refresh,
    download,
    install,
    setChannel,
  }
}

/** Calcola l'avviso di aggiornamento non ancora visto (preferenza server `update.seen`). */
export function useUpdateNotice() {
  const { data } = useQuery({
    queryKey: updateKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/update')),
    refetchInterval: (query) => (BUSY_PHASES.has(query.state.data?.progress?.phase ?? '') ? 3000 : false),
  })
  const [seen, setSeen] = usePreference<string | null>('update.seen', null)
  const { notice, seenKey } = computeUpdateNotice(data as AppUpdate | undefined, seen)

  const markSeen = useCallback(() => {
    if (seenKey && seen !== seenKey) {
      setSeen(seenKey)
    }
  }, [seen, seenKey, setSeen])

  return { notice, seenKey, markSeen }
}

/** Durante l'installazione RT si spegne e riparte: quando l'API risponde con la versione nuova
 * la pagina si ricarica. */
export function useReloadWhenUpdated(target: string | null) {
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!target) return
    const tick = async () => {
      try {
        const res = await fetch('/api/v1/health', { cache: 'no-store' })
        const body = res.ok ? ((await res.json()) as { version?: string }) : null
        if (body?.version === target) {
          window.location.reload()
          return
        }
      } catch {
        /* RT è spento durante l'installazione: si riprova */
      }
      timer.current = window.setTimeout(tick, 2000)
    }
    timer.current = window.setTimeout(tick, 2000)
    return () => window.clearTimeout(timer.current)
  }, [target])
}
