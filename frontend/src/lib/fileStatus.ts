import { useSyncExternalStore } from 'react'
import { saveFile } from '@/lib/fileExport'

export function isIosDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export type FileStatusState =
  | { kind: 'idle' }
  | { kind: 'busy'; message: string }
  | {
      kind: 'ready'
      label: string
      file: File
      isShare?: boolean
      shareTitle?: string
      onShare?: (file: File) => Promise<void>
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
  promise: Promise<File>,
  options: {
    busyMessage: string
    doneLabel: string
    isShare?: boolean
    shareTitle?: string
    onShare?: (file: File) => Promise<void>
  },
): Promise<File | null> {
  const start = Date.now()
  setFileStatus({ kind: 'busy', message: options.busyMessage })
  try {
    const file = await promise
    const duration = Date.now() - start
    const requiresTouch = duration > 1500 || isIosDevice()

    if (requiresTouch) {
      setFileStatus({
        kind: 'ready',
        label: options.doneLabel,
        file,
        isShare: options.isShare,
        shareTitle: options.shareTitle,
        onShare: options.onShare,
      })
    } else {
      if (options.isShare && options.onShare) {
        try {
          await options.onShare(file)
          setFileStatus({ kind: 'done', label: options.doneLabel, filename: file.name })
        } catch (shareError: unknown) {
          const err = shareError as { name?: string; message?: string }
          if (err?.name === 'NotAllowedError') {
            setFileStatus({
              kind: 'ready',
              label: options.doneLabel,
              file,
              isShare: true,
              shareTitle: options.shareTitle,
              onShare: options.onShare,
            })
          } else if (err?.name === 'AbortError') {
            clearFileStatus()
          } else {
            setFileStatus({ kind: 'error', message: err?.message ?? 'Condivisione non riuscita' })
          }
        }
      } else {
        saveFile(file)
        setFileStatus({ kind: 'done', label: options.doneLabel, filename: file.name })
      }
    }
    return file
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error)
    setFileStatus({ kind: 'error', message: msg })
    return null
  }
}
