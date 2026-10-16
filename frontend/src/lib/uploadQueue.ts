/**
 * Coda dei caricamenti della nuova lezione (IM2). Il trasferimento dei file non dipende dalla
 * finestra di import: chiudendola il caricamento continua, e un secondo import parte quando il
 * primo ha finito di inviare (uno alla volta, per non dividere la banda). Il job sul server
 * nasce solo a trasferimento finito; fino ad allora la scheda di RT deve restare aperta, e
 * `useUploadGuard` chiede conferma prima di chiuderla.
 */
import { useEffect, useSyncExternalStore } from 'react'

import type { UploadProgress } from '@/api/upload'

export type UploadState = 'queued' | 'uploading' | 'failed'

export type UploadItem = {
  id: string
  label: string
  files: string[]
  loaded: number
  total: number | null
  state: UploadState
  error: unknown
}

export type UploadSend<T> = (onProgress: (progress: UploadProgress) => void, signal: AbortSignal) => Promise<T>

type Task = {
  id: string
  send: UploadSend<unknown>
  controller: AbortController
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
}

let items: UploadItem[] = []
const tasks: Task[] = []
const listeners = new Set<() => void>()
let running = false
// Il caricamento in corso è già fuori da `tasks`: l'annullamento lo ritrova da qui.
let current: Task | null = null
let counter = 0

function emit() {
  for (const listener of listeners) listener()
}

function patch(id: string, change: Partial<UploadItem>) {
  items = items.map((item) => (item.id === id ? { ...item, ...change } : item))
  emit()
}

function remove(id: string) {
  items = items.filter((item) => item.id !== id)
  emit()
}

async function pump() {
  if (running) return
  running = true
  try {
    for (let task = tasks.shift(); task; task = tasks.shift()) {
      if (task.controller.signal.aborted) continue
      current = task
      patch(task.id, { state: 'uploading' })
      try {
        const value = await task.send(
          (progress) => patch(task.id, { loaded: progress.loaded, total: progress.total }),
          task.controller.signal,
        )
        // Il job esiste: da qui lo segue la pagina Job.
        remove(task.id)
        task.resolve(value)
      } catch (error) {
        if (task.controller.signal.aborted) remove(task.id)
        else patch(task.id, { state: 'failed', error })
        task.reject(error)
      } finally {
        current = null
      }
    }
  } finally {
    running = false
  }
}

/** Mette in coda un caricamento; la promessa si risolve con la risposta del server. */
export function enqueueUpload<T>(label: string, files: File[], send: UploadSend<T>): { id: string; done: Promise<T> } {
  counter += 1
  const id = `up-${counter}`
  const total = files.reduce((sum, file) => sum + file.size, 0)
  items = [...items, { id, label, files: files.map((f) => f.name), loaded: 0, total, state: 'queued', error: null }]
  emit()
  const done = new Promise<T>((resolve, reject) => {
    tasks.push({ id, send: send as UploadSend<unknown>, controller: new AbortController(), resolve: resolve as (v: unknown) => void, reject })
  })
  // Chi chiude la finestra non aspetta la promessa: il rifiuto non deve finire fra gli errori non gestiti.
  done.catch(() => undefined)
  void pump()
  return { id, done }
}

/** Annulla un caricamento in coda o in corso (o toglie dalla lista uno fallito). */
export function cancelUpload(id: string) {
  const index = tasks.findIndex((task) => task.id === id)
  if (index >= 0) {
    const [task] = tasks.splice(index, 1)
    task.controller.abort()
    task.reject(new DOMException('Caricamento annullato', 'AbortError'))
    remove(id)
    return
  }
  if (current?.id === id) current.controller.abort()
  else if (items.find((item) => item.id === id)?.state === 'failed') remove(id)
}

export function isUploadActive(item: UploadItem) {
  return item.state === 'queued' || item.state === 'uploading'
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const snapshot = () => items

export function useUploads(): UploadItem[] {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}

export function useUpload(id: string | null): UploadItem | null {
  const all = useUploads()
  return id ? (all.find((item) => item.id === id) ?? null) : null
}

/** Finché un caricamento è in coda o in corso, chiudere o ricaricare la scheda chiede conferma
 * (il testo lo sceglie il browser). */
export function useUploadGuard() {
  const active = useUploads().some(isUploadActive)
  useEffect(() => {
    if (!active) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [active])
}

/** Solo per i test. */
export function resetUploadsForTests() {
  for (const task of tasks.splice(0)) task.controller.abort()
  current?.controller.abort()
  current = null
  items = []
  running = false
  emit()
}
