import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useJobEvents } from './jobs'

class Source extends EventTarget {
  static current: Source
  readyState = 1
  onopen = null
  onerror = null
  onmessage = null
  closed = false
  constructor() { super(); Source.current = this }
  close() { this.closed = true }
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('il registro SSE conserva inizio e fine di un’unità e rilegge il job', () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', Source)
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const { result, unmount } = renderHook(() => useJobEvents('parte', { state: 'running', lesson_id: 7 }), { wrapper })
  const source = Source.current
  act(() => {
    for (const [id, type] of [[1, 'review_unit_started'], [2, 'review_unit_done']] as const) {
      source.dispatchEvent(new MessageEvent(type, { data: JSON.stringify({ id, type, job_id: 'parte', payload: { unit_id: '1.1' } }) }))
    }
    vi.advanceTimersByTime(300)
  })
  expect(result.current.events.map(event => event.type)).toEqual(['review_unit_started', 'review_unit_done'])
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['jobs', 'job', 'parte'] })
  unmount()
  expect(source.closed).toBe(true)
})
