import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'
import { jobKeys } from '@/api/jobs'
import { decisionLink, isActive, jobTypeLabel, QUIET_JOB_TYPES } from '@/lib/jobs'
import { isUploadActive, useUploads, type UploadItem } from '@/lib/uploadQueue'
import { isAppWindow } from '@/lib/zoom'

export type Job = Schemas['Job']

export function computeJobsBadgeCount(
  jobs: { state: string }[] | undefined,
  uploads: UploadItem[],
): number {
  const active = (jobs ?? []).filter((j) => isActive(j.state)).length
  const waiting = (jobs ?? []).filter((j) => j.state === 'waiting_for_decision').length
  const uploading = uploads.filter(isUploadActive).length
  return active + waiting + uploading
}

/** Hook che gestisce il badge nel Dock (Mac) e le notifiche di sistema quando un job termina. */
export function useDesktopJobSignals() {
  const isApp = isAppWindow()
  const uploads = useUploads()
  const jobs = useQuery({
    queryKey: jobKeys.list({ limit: 50 }),
    queryFn: () => unwrap(api.GET('/api/v1/jobs', { params: { query: { limit: 50 } } })),
    enabled: isApp,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const prevStatesRef = useRef<Map<string, string> | null>(null)

  useEffect(() => {
    if (!isApp) return
    const pyApi = window.pywebview?.api
    if (!pyApi) return

    const count = computeJobsBadgeCount(jobs.data, uploads)
    if (pyApi.badge) {
      pyApi.badge(count)
    }

    if (!jobs.data) return

    if (prevStatesRef.current === null) {
      // Al primo caricamento della lista non notifica niente: servono due letture per vedere una transizione.
      const initialMap = new Map<string, string>()
      for (const j of jobs.data) {
        initialMap.set(j.id, j.state)
      }
      prevStatesRef.current = initialMap
      return
    }

    const prevMap = prevStatesRef.current
    const newMap = new Map<string, string>()

    for (const j of jobs.data) {
      newMap.set(j.id, j.state)
      const prevState = prevMap.get(j.id)

      const isTransition =
        prevState !== undefined &&
        isActive(prevState) &&
        (j.state === 'succeeded' || j.state === 'failed' || j.state === 'waiting_for_decision')

      if (isTransition) {
        if (QUIET_JOB_TYPES.has(j.type)) {
          continue
        }
        const notInForeground =
          typeof document !== 'undefined' &&
          (document.visibilityState === 'hidden' || !document.hasFocus())

        if (notInForeground && pyApi.notifica) {
          const titolo = jobTypeLabel(j)
          const esito =
            j.state === 'succeeded'
              ? 'finito'
              : j.state === 'failed'
                ? 'non riuscito'
                : 'serve la tua decisione'
          const lTitle =
            (j.payload?.lesson_title as string) ||
            (j.payload?.titolo as string) ||
            ''
          const testo = lTitle ? `${lTitle}: ${esito}` : esito
          const percorso = decisionLink(j) || `/job/${j.id}`
          pyApi.notifica(titolo, testo, percorso)
        }
      }
    }

    prevStatesRef.current = newMap
  }, [isApp, jobs.data, uploads])
}
