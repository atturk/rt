import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage } from '@/api/client'
import type { AutoSaveState } from './ui'

type MutationLike<TPayload> = {
  mutate: (payload: TPayload, options?: { onSuccess?: () => void; onError?: (err: unknown) => void }) => void
}

function defaultEquals<T>(a: T, b: T): boolean {
  if (Object.is(a, b)) return true
  if (typeof a === 'object' && typeof b === 'object' && a !== null && b !== null) {
    return JSON.stringify(a) === JSON.stringify(b)
  }
  return false
}

/**
 * Salvataggio automatico per controlli di testo, numeri, select e switch.
 * - `delay === 0`: salva appena il valore cambia (es. select/switch).
 * - `delay > 0` (predefinito 600 ms): salva dopo `delay` ms dall'ultima modifica oppure su `flush()` (blur).
 * Espone `status` ('idle' | 'saving' | 'saved' | 'error'), `error` e `retry`.
 */
export function useAutoSave<TValue, TPayload = TValue>(
  mutation: MutationLike<TPayload>,
  value: TValue,
  options?: {
    delay?: number
    enabled?: boolean
    initial?: TValue
    serialize?: (value: TValue) => TPayload
    equals?: (a: TValue, b: TValue) => boolean
  },
): AutoSaveState & {
  flush: () => void
  saveNow: (override?: TValue) => void
  reset: () => void
} {
  const delay = options?.delay ?? 600
  const enabled = options?.enabled ?? true
  const equals = options?.equals ?? defaultEquals
  const initialValue = options && 'initial' in options ? (options.initial as TValue) : value

  const [status, setStatus] = useState<AutoSaveState['status']>('idle')
  const [error, setError] = useState<string | null>(null)

  const committedRef = useRef<TValue>(initialValue)
  const inFlightRef = useRef<TValue | null>(null)
  const latestValueRef = useRef<TValue>(value)
  const lastFailedRef = useRef<{ value: TValue; payload: TPayload } | null>(null)
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const mutationRef = useRef(mutation)
  const serializeRef = useRef(options?.serialize)
  const equalsRef = useRef(equals)

  useEffect(() => {
    latestValueRef.current = value
    mutationRef.current = mutation
    serializeRef.current = options?.serialize
    equalsRef.current = equals
  })

  // Sincronizza il valore iniziale quando il backend cambia dall'esterno (senza bozze pendenti).
  const prevInitialRef = useRef<TValue>(initialValue)
  useEffect(() => {
    if (!equalsRef.current(initialValue, prevInitialRef.current)) {
      prevInitialRef.current = initialValue
      committedRef.current = initialValue
    }
  }, [initialValue])

  useEffect(() => {
    return () => {
      clearTimeout(debounceTimerRef.current)
      clearTimeout(savedTimerRef.current)
    }
  }, [])

  const runSave = useCallback((targetValue: TValue) => {
    clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = undefined
    if (inFlightRef.current !== null && equalsRef.current(inFlightRef.current, targetValue)) {
      return
    }
    const payload = serializeRef.current
      ? serializeRef.current(targetValue)
      : (targetValue as unknown as TPayload)

    inFlightRef.current = targetValue
    lastFailedRef.current = null
    clearTimeout(savedTimerRef.current)
    setStatus('saving')
    setError(null)

    mutationRef.current.mutate(payload, {
      onSuccess: () => {
        if (inFlightRef.current !== null && equalsRef.current(inFlightRef.current, targetValue)) {
          inFlightRef.current = null
        }
        committedRef.current = targetValue
        setStatus('saved')
        clearTimeout(savedTimerRef.current)
        savedTimerRef.current = setTimeout(() => {
          setStatus((current) => (current === 'saved' ? 'idle' : current))
        }, 1500)
      },
      onError: (err) => {
        if (inFlightRef.current !== null && equalsRef.current(inFlightRef.current, targetValue)) {
          inFlightRef.current = null
        }
        lastFailedRef.current = { value: targetValue, payload }
        setStatus('error')
        setError(errorMessage(err))
      },
    })
  }, [])

  useEffect(() => {
    clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = undefined
    if (!enabled) return
    if (equalsRef.current(value, committedRef.current)) return
    if (inFlightRef.current !== null && equalsRef.current(inFlightRef.current, value)) return

    if (delay <= 0) {
      // oxlint-disable-next-line react/set-state-in-effect -- salvataggio immediato per delay=0
      runSave(value)
      return
    }
    debounceTimerRef.current = setTimeout(() => {
      runSave(latestValueRef.current)
    }, delay)
    return () => {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = undefined
    }
  }, [value, delay, enabled, runSave])

  const flush = useCallback(() => {
    clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = undefined
    if (!enabled) return
    const current = latestValueRef.current
    if (equalsRef.current(current, committedRef.current)) return
    runSave(current)
  }, [enabled, runSave])

  const saveNow = useCallback(
    (override?: TValue) => {
      const target = override !== undefined ? override : latestValueRef.current
      latestValueRef.current = target
      runSave(target)
    },
    [runSave],
  )

  const retry = useCallback(() => {
    if (lastFailedRef.current) {
      runSave(lastFailedRef.current.value)
    } else if (enabled && !equalsRef.current(latestValueRef.current, committedRef.current)) {
      runSave(latestValueRef.current)
    }
  }, [enabled, runSave])

  const reset = useCallback(() => {
    clearTimeout(debounceTimerRef.current)
    clearTimeout(savedTimerRef.current)
    inFlightRef.current = null
    lastFailedRef.current = null
    setStatus('idle')
    setError(null)
  }, [])

  return { status, error, flush, saveNow, retry, reset }
}
