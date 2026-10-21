import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'
import { isAppWindow } from '@/lib/zoom'

export type AppUpdate = Schemas['AppUpdate']
export const updateKey = ['system', 'update'] as const

export function useAppUpdate() {
  const client = useQueryClient()
  const update = useQuery({
    queryKey: updateKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/update')),
    refetchInterval: (query) => (query.state.data?.progress?.phase === 'downloading' ? 1000 : false),
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

/** Hook per aprire il popup degli aggiornamenti nella finestra principale dell'app pywebview. */
export function useUpdatePopup() {
  const isApp = isAppWindow()
  const { data } = useQuery({
    queryKey: updateKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/update')),
    enabled: isApp,
    refetchInterval: (query) => (query.state.data?.progress?.phase === 'downloading' ? 1000 : false),
  })

  const prevPhaseRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (!isApp || !data) return
    const pyApi = window.pywebview?.api
    if (!pyApi?.apri_aggiornamento) return

    const phase = data.progress?.phase
    const prevPhase = prevPhaseRef.current
    prevPhaseRef.current = phase

    // Quando un download avviato dal popup finisce mentre il popup è chiuso, riapre il popup
    if (prevPhase === 'downloading' && phase === 'ready') {
      pyApi.apri_aggiornamento()
      return
    }

    if (data.ready) {
      const shownKey = `rt-update-ready-shown:${data.latest}`
      if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(shownKey) !== '1') {
        sessionStorage.setItem(shownKey, '1')
        pyApi.apri_aggiornamento()
      }
      return
    }

    if (data.available && data.latest) {
      const shownKey = `rt-update-shown:${data.latest}`
      if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(shownKey) !== '1') {
        sessionStorage.setItem(shownKey, '1')
        pyApi.apri_aggiornamento()
      }
    }
  }, [isApp, data])
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
