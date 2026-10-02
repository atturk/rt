import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { keysForEvent, useLiveUpdates, type LiveJobEvent } from './liveUpdates'

class FakeEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  static all: FakeEventSource[] = []
  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  listeners: Record<string, ((m: MessageEvent<string>) => void)[]> = {}
  closed = false
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void) {
    ;(this.listeners[type] ??= []).push(fn)
  }
  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }
  open() {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }
  emit(event: LiveJobEvent) {
    for (const fn of this.listeners.job ?? []) fn({ data: JSON.stringify(event), lastEventId: String(event.id) } as MessageEvent<string>)
  }
  fail() {
    this.readyState = FakeEventSource.CLOSED
    this.onerror?.()
  }
}

const event = (over: Partial<LiveJobEvent>): LiveJobEvent => ({ id: 1, job_id: 'j1', job_type: 'run_phase', lesson_id: 7, type: 'phase_progress', ...over })
const has = (keys: unknown[], key: unknown[]) => keys.some((k) => JSON.stringify(k) === JSON.stringify(key))

describe('keysForEvent', () => {
  it("l'avanzamento aggiorna solo i job", () => {
    const keys = keysForEvent(event({}))
    expect(has(keys, ['jobs'])).toBe(true)
    expect(has(keys, ['job', 'j1'])).toBe(true)
    expect(has(keys, ['lesson', 7, 'jobs'])).toBe(true)
    expect(has(keys, ['lessons'])).toBe(false)
    expect(has(keys, ['lesson', 7])).toBe(false)
  })

  it('la fine di un job rilegge la lezione, e recall e rilevanza per i loro job', () => {
    const keys = keysForEvent(event({ type: 'job_finished', job_type: 'unit_relevance' }))
    for (const key of [['lessons'], ['lesson', 7], ['outline', 7], ['relevance', 7], ['recall'], ['recall-subject'], ['costs']]) {
      expect(has(keys, key)).toBe(true)
    }
  })

  it("l'arricchimento si aggiorna a ogni evento dei suoi job", () => {
    expect(has(keysForEvent(event({ job_type: 'enrichment_generate' })), ['enrichment'])).toBe(true)
  })
})

describe('useLiveUpdates', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeEventSource.all = []
    vi.stubGlobal('EventSource', FakeEventSource)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function setup(enabled = true) {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const view = renderHook(({ on }) => useLiveUpdates(on), { wrapper, initialProps: { on: enabled } })
    const invalidated = () => invalidate.mock.calls.map(([filters]) => filters?.queryKey).filter(Boolean)
    return { view, invalidate, invalidated }
  }

  it('apre un solo stream e invalida le query degli eventi a raffica', () => {
    const { invalidate, invalidated } = setup()
    expect(FakeEventSource.all).toHaveLength(1)
    expect(FakeEventSource.all[0].url).toBe('/api/v1/events')
    act(() => FakeEventSource.all[0].open())
    invalidate.mockClear()
    act(() => {
      FakeEventSource.all[0].emit(event({ id: 5 }))
      FakeEventSource.all[0].emit(event({ id: 6 }))
    })
    expect(invalidate).not.toHaveBeenCalled()
    act(() => void vi.advanceTimersByTime(300))
    // stesse chiavi una volta sola
    expect(invalidated().filter((k) => JSON.stringify(k) === '["jobs"]')).toHaveLength(1)
    expect(has(invalidated(), ['job', 'j1'])).toBe(true)
  })

  it('dopo un errore che chiude lo stream riapre con attesa crescente, da dopo l\'ultimo evento', () => {
    setup()
    const first = FakeEventSource.all[0]
    act(() => {
      first.open()
      first.emit(event({ id: 42 }))
      first.fail()
    })
    expect(first.closed).toBe(true)
    act(() => void vi.advanceTimersByTime(999))
    expect(FakeEventSource.all).toHaveLength(1)
    act(() => void vi.advanceTimersByTime(1))
    expect(FakeEventSource.all).toHaveLength(2)
    expect(FakeEventSource.all[1].url).toBe('/api/v1/events?after=42')
    act(() => FakeEventSource.all[1].fail())
    act(() => void vi.advanceTimersByTime(1999))
    expect(FakeEventSource.all).toHaveLength(2)
    act(() => void vi.advanceTimersByTime(1))
    expect(FakeEventSource.all).toHaveLength(3)
  })

  it('mentre lo stream è giù rilegge comunque i job ogni tanto', () => {
    const { invalidate, invalidated } = setup()
    act(() => FakeEventSource.all[0].fail())
    invalidate.mockClear()
    act(() => void vi.advanceTimersByTime(10_000))
    expect(has(invalidated(), ['jobs'])).toBe(true)
  })

  it("senza accesso non apre nulla e all'uscita chiude lo stream", () => {
    const { view } = setup(false)
    expect(FakeEventSource.all).toHaveLength(0)
    view.rerender({ on: true })
    expect(FakeEventSource.all).toHaveLength(1)
    view.unmount()
    expect(FakeEventSource.all[0].closed).toBe(true)
  })
})
