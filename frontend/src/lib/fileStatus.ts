import { useSyncExternalStore } from 'react'
import { api } from '@/api/client'
import { canShareFiles, fetchExport, saveFile, shareFile } from '@/lib/fileExport'

export type ExportFileInfo = {
  name: string
  size?: number
}

export type FileStatusState =
  | { kind: 'idle' }
  | {
      kind: 'busy'
      message: string
      onCancel?: () => void
    }
  | {
      kind: 'ready'
      label: string
      filename?: string
      file?: File
      files?: ExportFileInfo[]
      skippedMessage?: string
      canShare?: boolean
      isShare?: boolean
      shareTitle?: string
      onSave: () => Promise<void> | void
      onShare?: ((file: File) => Promise<void>) | (() => Promise<void>)
      onCancel?: () => Promise<void> | void
    }
  | { kind: 'done'; label: string; filename: string }
  | { kind: 'error'; message: string }

type Listener = () => void
let listeners: Listener[] = []
let currentState: FileStatusState = { kind: 'idle' }
let autoCloseTimer: ReturnType<typeof setTimeout> | null = null

function emit() {
  for (const listener of listeners) listener()
}

export function getFileStatusSnapshot(): FileStatusState {
  return currentState
}

export function subscribeFileStatus(listener: Listener): () => void {
  listeners.push(listener)
  return () => {
    listeners = listeners.filter((l) => l !== listener)
  }
}

export function setFileStatus(state: FileStatusState): void {
  if (autoCloseTimer) {
    clearTimeout(autoCloseTimer)
    autoCloseTimer = null
  }
  currentState = state
  emit()
  if (state.kind === 'done') {
    autoCloseTimer = setTimeout(() => {
      currentState = { kind: 'idle' }
      emit()
    }, 4000)
  }
}

export function clearFileStatus(): void {
  if (autoCloseTimer) {
    clearTimeout(autoCloseTimer)
    autoCloseTimer = null
  }
  currentState = { kind: 'idle' }
  emit()
}

export function useFileStatus(): FileStatusState {
  return useSyncExternalStore(subscribeFileStatus, getFileStatusSnapshot, () => ({ kind: 'idle' }))
}

/** Traccia lo stato di esportazione/preparazione di un file con la barra di stato. */
export async function trackFileExport(
  promiseOrFn: Promise<File> | ((signal: AbortSignal) => Promise<File>),
  options: {
    busyMessage: string
    doneLabel: string
    fileType?: string
    url?: string
    isShare?: boolean
    shareTitle?: string
    onShare?: (file: File) => Promise<void>
  },
): Promise<File | null> {
  const controller = new AbortController()
  const cancel = () => {
    controller.abort()
    const pywebview = (window as unknown as { pywebview?: { api?: { pulisci_condivisione?: () => void } } }).pywebview
    pywebview?.api?.pulisci_condivisione?.()
    clearFileStatus()
  }

  setFileStatus({
    kind: 'busy',
    message: options.busyMessage,
    onCancel: cancel,
  })

  try {
    const promise = typeof promiseOrFn === 'function' ? promiseOrFn(controller.signal) : promiseOrFn
    const file = await promise
    if (controller.signal.aborted) {
      clearFileStatus()
      return null
    }

    const canShare = Boolean(options.isShare || options.onShare || canShareFiles(options.fileType || file.type || 'application/pdf'))
    const pywebview = (window as unknown as { pywebview?: { api?: { condividi?: (path: string) => Promise<{ ok?: boolean; errore?: string }>; pulisci_condivisione?: () => void } } }).pywebview

    const onSave = () => {
      saveFile(file)
      pywebview?.api?.pulisci_condivisione?.()
      setFileStatus({ kind: 'done', label: options.doneLabel, filename: file.name })
    }

    const onShare = canShare
      ? async () => {
          try {
            if (options.onShare) {
              await options.onShare(file)
            } else if (pywebview?.api?.condividi && options.url) {
              const res = await pywebview.api.condividi(options.url)
              if (res?.errore) {
                setFileStatus({ kind: 'error', message: res.errore })
                return
              }
            } else {
              await shareFile(file, { title: options.shareTitle })
            }
            pywebview?.api?.pulisci_condivisione?.()
            setFileStatus({ kind: 'done', label: options.doneLabel, filename: file.name })
          } catch (err: unknown) {
            const error = err as { name?: string; message?: string }
            if (error?.name === 'AbortError') {
              return
            }
            setFileStatus({ kind: 'error', message: error?.message ?? 'Condivisione non riuscita' })
          }
        }
      : undefined

    setFileStatus({
      kind: 'ready',
      label: options.doneLabel,
      filename: file.name,
      file,
      canShare,
      isShare: canShare,
      shareTitle: options.shareTitle,
      onSave,
      onShare,
      onCancel: cancel,
    })
    return file
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === 'AbortError') {
      clearFileStatus()
      return null
    }
    const msg = error instanceof Error ? error.message : String(error)
    setFileStatus({ kind: 'error', message: msg })
    return null
  }
}

/** Esporta più lezioni come job asincrono tracciato nel popup file-status. */
export async function exportLessonsMultiple(params: {
  ids: number[]
  format: 'pdf' | 'zip'
  name?: string
  study?: boolean
}): Promise<void> {
  const { ids, format, name = 'Lezioni selezionate', study = false } = params
  if (ids.length === 0) return

  let jobId: string | null = null
  let cancelled = false

  const cancelJob = async () => {
    cancelled = true
    if (jobId) {
      try {
        await api.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } })
      } catch {}
      try {
        await fetch(`/api/v1/lesson-exports/${jobId}`, { method: 'DELETE' })
      } catch {}
    }
    const pywebview = (window as unknown as { pywebview?: { api?: { pulisci_condivisione?: () => void } } }).pywebview
    pywebview?.api?.pulisci_condivisione?.()
    clearFileStatus()
  }

  setFileStatus({
    kind: 'busy',
    message: format === 'pdf' ? 'Preparo il PDF…' : 'Preparo le lezioni…',
    onCancel: cancelJob,
  })

  try {
    const postRes = await api.POST('/api/v1/lesson-exports', {
      body: { ids, format, name, study } as never,
    })
    if (postRes.error || !postRes.data) {
      const err = postRes.error as { message?: string }
      setFileStatus({ kind: 'error', message: err?.message || 'Esportazione non riuscita' })
      return
    }
    jobId = postRes.data.job_id

    // Attendi il completamento
    while (!cancelled) {
      await new Promise((r) => setTimeout(r, 400))
      if (cancelled) return

      const jobRes = await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: jobId } } })
      if (!jobRes.data) continue

      const job = jobRes.data
      if (job.state === 'running' || job.state === 'queued') {
        const msg = (job.progress?.message as string | undefined) || (format === 'pdf' ? 'Preparo il PDF…' : 'Preparo le lezioni…')
        setFileStatus({ kind: 'busy', message: msg, onCancel: cancelJob })
      } else if (job.state === 'failed') {
        setFileStatus({ kind: 'error', message: job.error || 'Nessuna lezione del gruppo ha un documento finale aggiornato.' })
        return
      } else if (job.state === 'succeeded') {
        break
      }
    }

    if (cancelled || !jobId) return

    const currentJobId = jobId
    let files: ExportFileInfo[] = []
    try {
      const filesRes = await fetch(`/api/v1/lesson-exports/${currentJobId}/files`)
      if (filesRes.ok) {
        files = (await filesRes.json()) as ExportFileInfo[]
      }
    } catch {}

    const jobInfoRes = await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: currentJobId } } })
    const res = (jobInfoRes.data?.result as { files?: string[]; included?: number; skipped?: number } | undefined)
    const included = res?.included ?? files.length
    const skipped = res?.skipped ?? (ids.length - included)

    if (files.length === 0 && res?.files) {
      files = res.files.map((f) => ({ name: f }))
    }

    const label = format === 'pdf'
      ? (files.length === 1 ? '1 PDF pronto' : `${files.length} PDF pronti`)
      : (files.length === 1 ? '1 lezione pronta (.rt)' : `${files.length} lezioni pronte (.rt)`)

    const skippedMessage = skipped > 0
      ? (skipped === 1 ? '(1 senza documento finale saltata)' : `(${skipped} senza documento finale saltate)`)
      : undefined

    const pywebview = (window as unknown as { pywebview?: { api?: { salva_esportazione?: (id: string) => Promise<{ ok?: boolean; annullato?: boolean; errore?: string }>; condividi_esportazione?: (id: string) => Promise<{ ok?: boolean; errore?: string }>; pulisci_condivisione?: () => void } } }).pywebview

    const isWindowsApp = typeof window !== 'undefined' && 'pywebview' in window && typeof navigator !== 'undefined' && /Win/i.test(navigator.platform || navigator.userAgent)
    let canShare = false
    if (!isWindowsApp) {
      if (pywebview?.api?.condividi_esportazione) {
        canShare = true
      } else if (typeof navigator !== 'undefined' && typeof navigator.canShare === 'function') {
        try {
          const dummies = files.map((f) => new File([''], f.name, { type: format === 'pdf' ? 'application/pdf' : 'application/zip' }))
          canShare = navigator.canShare({ files: dummies })
        } catch {
          canShare = false
        }
      }
    }

    const onSave = async () => {
      if (pywebview?.api?.salva_esportazione) {
        const result = await pywebview.api.salva_esportazione(currentJobId)
        if (result?.annullato) return
        if (result?.errore) {
          setFileStatus({ kind: 'error', message: result.errore })
          return
        }
        clearFileStatus()
      } else {
        const file = await fetchExport(`/api/v1/lesson-exports/${currentJobId}/file`)
        saveFile(file)
        clearFileStatus()
        fetch(`/api/v1/lesson-exports/${currentJobId}`, { method: 'DELETE' }).catch(() => {})
      }
    }

    const onShare = canShare
      ? async () => {
          if (pywebview?.api?.condividi_esportazione) {
            const result = await pywebview.api.condividi_esportazione(currentJobId)
            if (result?.errore) {
              setFileStatus({ kind: 'error', message: result.errore })
              return
            }
            clearFileStatus()
          } else {
            try {
              const fileObjects = await Promise.all(
                files.map((f) => fetchExport(`/api/v1/lesson-exports/${currentJobId}/files/${encodeURIComponent(f.name)}`))
              )
              await navigator.share({ files: fileObjects })
              clearFileStatus()
              fetch(`/api/v1/lesson-exports/${currentJobId}`, { method: 'DELETE' }).catch(() => {})
            } catch (err: unknown) {
              const error = err as { name?: string; message?: string }
              if (error?.name === 'AbortError') return
              setFileStatus({ kind: 'error', message: error?.message ?? 'Condivisione non riuscita' })
            }
          }
        }
      : undefined

    setFileStatus({
      kind: 'ready',
      label,
      files,
      skippedMessage,
      canShare,
      isShare: canShare,
      onSave,
      onShare,
      onCancel: async () => {
        await cancelJob()
      },
    })
  } catch (err: unknown) {
    const error = err as { message?: string }
    setFileStatus({ kind: 'error', message: error?.message || 'Esportazione non riuscita' })
  }
}
