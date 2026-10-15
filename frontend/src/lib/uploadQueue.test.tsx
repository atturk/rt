import { act, render, renderHook } from '@testing-library/react'
import { UploadList } from '@/components/jobs/UploadList'
import { cancelUpload, enqueueUpload, resetUploadsForTests, useUploadGuard, useUploads } from './uploadQueue'

type Pending = { resolve: (v: { job_id: string }) => void; reject: (e: unknown) => void; progress: (loaded: number) => void; signal: AbortSignal }

function deferredSend(calls: Pending[]) {
  return (onProgress: (p: { loaded: number; total: number | null }) => void, signal: AbortSignal) =>
    new Promise<{ job_id: string }>((resolve, reject) => {
      calls.push({ resolve, reject, progress: (loaded) => onProgress({ loaded, total: 10 }), signal })
      signal.addEventListener('abort', () => reject(new DOMException('Caricamento annullato', 'AbortError')))
    })
}

const file = (name: string) => new File(['0123456789'], name)

beforeEach(() => resetUploadsForTests())

describe('coda dei caricamenti', () => {
  it('un caricamento alla volta: il secondo parte quando il primo ha il job', async () => {
    const calls: Pending[] = []
    const { result } = renderHook(() => useUploads())
    let first!: Promise<{ job_id: string }>
    act(() => {
      first = enqueueUpload('A', [file('a.wav')], deferredSend(calls)).done
      enqueueUpload('B', [file('b.wav')], deferredSend(calls))
    })
    expect(calls).toHaveLength(1)
    expect(result.current.map((u) => u.state)).toEqual(['uploading', 'queued'])
    act(() => calls[0].progress(5))
    expect(result.current[0]).toMatchObject({ loaded: 5, total: 10 })
    await act(async () => {
      calls[0].resolve({ job_id: 'j1' })
      await first
    })
    expect(calls).toHaveLength(2)
    expect(result.current.map((u) => [u.label, u.state])).toEqual([['B', 'uploading']])
  })

  it('annullare interrompe quello in corso e toglie quello in coda; un errore resta nella riga', async () => {
    const calls: Pending[] = []
    const { result } = renderHook(() => useUploads())
    let a!: ReturnType<typeof enqueueUpload<{ job_id: string }>>
    let b!: ReturnType<typeof enqueueUpload<{ job_id: string }>>
    act(() => {
      a = enqueueUpload('A', [file('a.wav')], deferredSend(calls))
      b = enqueueUpload('B', [file('b.wav')], deferredSend(calls))
      enqueueUpload('C', [file('c.wav')], deferredSend(calls))
    })
    act(() => cancelUpload(b.id))
    await expect(b.done).rejects.toThrow('annullato')
    await act(async () => {
      cancelUpload(a.id)
      await a.done.catch(() => undefined)
    })
    expect(calls[0].signal.aborted).toBe(true)
    expect(result.current.map((u) => u.label)).toEqual(['C'])
    await act(async () => {
      calls[1].reject(new Error('Rete non raggiungibile'))
      await Promise.resolve()
    })
    expect(result.current[0]).toMatchObject({ label: 'C', state: 'failed' })
    const { getByTestId } = render(<UploadList />)
    expect(getByTestId('upload-row')).toHaveTextContent('Rete non raggiungibile')
  })

  it('chiudere la scheda chiede conferma solo mentre si carica', async () => {
    const calls: Pending[] = []
    renderHook(() => useUploadGuard())
    const fire = () => {
      const event = new Event('beforeunload', { cancelable: true })
      window.dispatchEvent(event)
      return event.defaultPrevented
    }
    expect(fire()).toBe(false)
    let done!: Promise<{ job_id: string }>
    act(() => {
      done = enqueueUpload('A', [file('a.wav')], deferredSend(calls)).done
    })
    expect(fire()).toBe(true)
    await act(async () => {
      calls[0].resolve({ job_id: 'j1' })
      await done
    })
    expect(fire()).toBe(false)
  })
})
