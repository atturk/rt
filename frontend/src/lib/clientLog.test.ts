import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installClientLog, reportClientLog, resetClientLogForTests } from './clientLog'

function sentBodies(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.map(([, init]) => JSON.parse((init as RequestInit).body as string))
}

describe('clientLog', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    resetClientLogForTests()
    fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    document.cookie = 'rt_csrf=abc'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('manda il messaggio con pagina, stack e header CSRF', () => {
    window.history.pushState({}, '', '/lezioni/3?panel=studio')
    reportClientLog('error', 'TypeError: x', 'at Study')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/system/client-log')
    expect((init as RequestInit).headers).toMatchObject({ 'X-CSRF-Token': 'abc' })
    expect(sentBodies(fetchMock)[0]).toEqual({ level: 'error', message: 'TypeError: x', page: '/lezioni/3?panel=studio', stack: 'at Study' })
  })

  it('non ripete lo stesso messaggio entro un minuto e ignora il rumore del browser', () => {
    reportClientLog('warn', 'avviso')
    reportClientLog('warn', 'avviso')
    reportClientLog('error', 'ResizeObserver loop completed with undelivered notifications.')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('una rete giù non rompe la pagina', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    expect(() => reportClientLog('error', 'qualcosa')).not.toThrow()
    await Promise.resolve()
  })

  it('inoltra console.error, console.warn e le promesse rifiutate', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    installClientLog()
    console.error('Errore di rete', new Error('boom'))
    console.warn('Attenzione', { codice: 7 })
    window.dispatchEvent(Object.assign(new Event('unhandledrejection'), { reason: new Error('rifiutata') }))
    const bodies = sentBodies(fetchMock)
    expect(bodies.map((b) => b.message)).toEqual([
      'Errore di rete Error: boom',
      'Attenzione {"codice":7}',
      'Promessa rifiutata: Error: rifiutata',
    ])
    expect(bodies[0].stack).toContain('boom')
    expect(errorSpy).toHaveBeenCalled()
    expect(warnSpy).toHaveBeenCalled()
    errorSpy.mockRestore()
    warnSpy.mockRestore()
  })
})
