// Contratto 4.2.5b2: alla fusione si passa a schema.d.ts
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, unwrap } from './client'
import { invalidateAfterJob } from './jobs'
import { jobFinished, useJobStatus } from './jobStatus'

export type SourceKind = 'audio' | 'appunti' | 'materiale'

export type SourcePartItem = {
  nome: string
  durata?: string | null
  durata_s?: number | null
}

export type SourceItem = {
  id: string
  tipo: SourceKind
  file: string
  impronta: string
  aggiunta_il: string
  ordine: number
  nome: string
  durata_s?: number | null
  pagine?: number | null
  parole?: number | null
  usata: boolean
  parti?: SourcePartItem[] | null
}

export type LastUpdateInfo = {
  modo: 'extend' | 'rebuild'
  unita_nuove: number
  unita_cambiate: number
  il: string
}

export type SourcesView = {
  sources: SourceItem[]
  has_unused_sources: boolean
  can_undo: boolean
  ultimo_aggiornamento?: LastUpdateInfo | null
  principale: string
  ordine_usato: string[]
  principale_usato: string | null
  solo_ricostruzione: boolean
  fonti_tolte_usate?: string[]
}

export type LessonVersion = {
  id: string
  il: string
  modo: 'import' | 'extend' | 'rebuild' | 'restore'
  fonti_aggiunte: string[]
  unita_nuove: number
  unita_cambiate: number
  attuale: boolean
}

export const sourcesKeys = {
  all: (lessonId: number) => ['lessons', lessonId, 'sources'] as const,
  versions: (lessonId: number) => ['lessons', lessonId, 'versions'] as const,
}

export const sourcesApi = {
  getSources: (lessonId: number): Promise<SourcesView> =>
    unwrap((api as any).GET(`/api/v1/lessons/${lessonId}/sources`)),

  addAudio: (
    lessonId: number,
    file: File | File[],
    ordine?: number,
    unisci: boolean = true,
  ): Promise<SourceItem | SourceItem[]> => {
    const form = new FormData()
    form.append('tipo', 'audio')
    const files = Array.isArray(file) ? file : [file]
    for (const f of files) form.append('file', f, f.name)
    form.append('unisci', String(unisci))
    if (ordine !== undefined) form.append('ordine', String(ordine))
    return unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/sources`, { bodySerializer: () => form, body: form }))
  },

  addNotes: (lessonId: number, testo: string, ordine?: number): Promise<SourceItem> => {
    const form = new FormData()
    form.append('tipo', 'appunti')
    form.append('testo', testo)
    if (ordine !== undefined) form.append('ordine', String(ordine))
    return unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/sources`, { bodySerializer: () => form, body: form }))
  },

  addMaterials: (lessonId: number, files: File[]): Promise<SourceItem[]> => {
    const form = new FormData()
    form.append('tipo', 'materiale')
    for (const f of files) form.append('file', f, f.name)
    return unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/sources`, { bodySerializer: () => form, body: form }))
  },

  deleteSource: (lessonId: number, sid: string): Promise<void> =>
    unwrap((api as any).DELETE(`/api/v1/lessons/${lessonId}/sources/${encodeURIComponent(sid)}`)),

  restoreRemoved: (lessonId: number): Promise<SourcesView> =>
    unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/sources/restore-removed`)),

  reorder: (lessonId: number, ids: string[]): Promise<SourcesView> =>
    unwrap((api as any).PUT(`/api/v1/lessons/${lessonId}/sources/order`, { body: { ids } })),

  setPrimary: (lessonId: number, id: string): Promise<SourcesView> =>
    unwrap((api as any).PUT(`/api/v1/lessons/${lessonId}/sources/primary`, { body: { id } })),

  updateLesson: (lessonId: number, mode: 'extend' | 'rebuild'): Promise<{ job_id: string }> =>
    unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/update`, { body: { mode } })),

  undoUpdate: (lessonId: number): Promise<{ status: string }> =>
    unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/update/undo`)),

  getVersions: (lessonId: number): Promise<LessonVersion[]> =>
    unwrap((api as any).GET(`/api/v1/lessons/${lessonId}/versions`)),

  restoreVersion: (lessonId: number, vid: string): Promise<{ job_id: string }> =>
    unwrap((api as any).POST(`/api/v1/lessons/${lessonId}/versions/${encodeURIComponent(vid)}/restore`)),
}

export function useSources(lessonId: number) {
  return useQuery({
    queryKey: sourcesKeys.all(lessonId),
    queryFn: () => sourcesApi.getSources(lessonId),
    enabled: Number.isFinite(lessonId),
  })
}

export function useVersions(lessonId: number, enabled = true) {
  return useQuery({
    queryKey: sourcesKeys.versions(lessonId),
    queryFn: () => sourcesApi.getVersions(lessonId),
    enabled: Number.isFinite(lessonId) && enabled,
  })
}

export function useReorderSources(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => sourcesApi.reorder(lessonId, ids),
    onSuccess: (data) => {
      queryClient.setQueryData(sourcesKeys.all(lessonId), data)
    },
  })
}

export function useSetPrimarySource(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => sourcesApi.setPrimary(lessonId, id),
    onSuccess: (data) => {
      queryClient.setQueryData(sourcesKeys.all(lessonId), data)
    },
  })
}

export function useDeleteSource(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sid: string) => sourcesApi.deleteSource(lessonId, sid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all(lessonId) })
    },
  })
}

export function useUpdateLesson(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (mode: 'extend' | 'rebuild') => sourcesApi.updateLesson(lessonId, mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all(lessonId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.versions(lessonId) })
    },
  })
}

export function useUndoUpdate(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => sourcesApi.undoUpdate(lessonId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all(lessonId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.versions(lessonId) })
    },
  })
}

export function useRestoreVersion(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vid: string) => sourcesApi.restoreVersion(lessonId, vid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all(lessonId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.versions(lessonId) })
    },
  })
}

/**
 * Ordine completo per "Rimetti com'era": PUT order vuole ogni fonte attuale una volta sola,
 * quindi le parti audio già usate tornano nell'ordine di ordine_usato dentro i posti che occupano
 * ora, e tutte le altre fonti (anche le nuove) restano dove sono.
 */
export function usedOrderIds(sources: SourceItem[], ordineUsato: string[]): string[] {
  const audio = new Set(sources.filter((s) => s.tipo === 'audio').map((s) => s.id))
  const used = ordineUsato.filter((id) => audio.has(id))
  const usedSet = new Set(used)
  let next = 0
  return sources.map((s) => (usedSet.has(s.id) ? used[next++] : s.id))
}

/**
 * Rimette ordine e principale dell'ultimo aggiornamento. Le due PUT vanno in sequenza: il lucchetto
 * della lezione non aspetta e due richieste insieme darebbero 409 lesson_busy.
 */
export function useResetSelection(lessonId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (view: SourcesView) => {
      let current = view.fonti_tolte_usate?.length ? await sourcesApi.restoreRemoved(lessonId) : view
      const ids = usedOrderIds(current.sources, current.ordine_usato ?? [])
      if (ids.length > 0 && ids.some((id, i) => id !== current.sources[i].id)) {
        current = await sourcesApi.reorder(lessonId, ids)
      }
      const primary = view.principale_usato
      if (primary && current.principale !== primary && current.sources.some((s) => s.id === primary)) {
        current = await sourcesApi.setPrimary(lessonId, primary)
      }
      return current
    },
    onSuccess: (data) => {
      queryClient.setQueryData(sourcesKeys.all(lessonId), data)
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: sourcesKeys.all(lessonId) })
    },
  })
}

/**
 * Segue il job di un aggiornamento o di un ripristino: avanzamento per la riga sopra il testo e,
 * a job finito, rilettura di fonti, versioni e lezione.
 */
export function useSourcesJob(lessonId: number) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const finished = jobFinished(job.data)
  const notified = useRef<string | null>(null)
  useEffect(() => {
    if (!jobId || !finished || notified.current === jobId) return
    notified.current = jobId
    invalidateAfterJob(queryClient, lessonId)
    void queryClient.invalidateQueries({ queryKey: ['lesson', lessonId] })
  }, [jobId, finished, lessonId, queryClient])
  const progress = job.data?.progress as { message?: string; current?: number; total?: number } | null | undefined
  const failed = job.data?.state === 'failed'
  return {
    jobId,
    start: setJobId,
    running: !!jobId && !finished && !job.isError,
    percent: progress?.total ? Math.round(((progress.current ?? 0) / progress.total) * 100) : null,
    message: progress?.message ?? null,
    error: job.isError
      ? errorMessage(job.error)
      : failed
        ? (job.data?.error ?? 'Aggiornamento non riuscito.')
        : null,
  }
}
