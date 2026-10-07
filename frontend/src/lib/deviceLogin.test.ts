import { describe, expect, it } from 'vitest'

import { deviceLoginUrl, isHttpsIp, isLoopback, normalizeOrigin, preferredOrigin } from './deviceLogin'

describe('deviceLogin', () => {
  it('riconosce gli indirizzi locali del Mac', () => {
    expect(isLoopback('http://127.0.0.1:8765')).toBe(true)
    expect(isLoopback('http://localhost:5173')).toBe(true)
    expect(isLoopback('https://mac.tail1234.ts.net')).toBe(false)
    expect(isLoopback('http://mac.local:8765')).toBe(false)
  })

  it('accetta un nome host senza schema e lo porta in https', () => {
    expect(normalizeOrigin('mac.tail1234.ts.net')).toBe('https://mac.tail1234.ts.net')
    expect(normalizeOrigin(' http://mac.local:8765/impostazioni ')).toBe('http://mac.local:8765')
    expect(normalizeOrigin('')).toBeNull()
    expect(normalizeOrigin('ftp://mac.local')).toBeNull()
  })

  it("rimette il codice monouso sull'indirizzo dell'altro dispositivo", () => {
    expect(deviceLoginUrl('http://127.0.0.1:8765/login?code=abc-_1', 'https://mac.tail1234.ts.net'))
      .toBe('https://mac.tail1234.ts.net/login?code=abc-_1')
    expect(deviceLoginUrl('http://127.0.0.1:8765/login', 'https://mac.tail1234.ts.net')).toBeNull()
  })

  it("riconosce l'IP in https, che col certificato di Tailscale non funziona", () => {
    expect(isHttpsIp('https://100.72.84.124')).toBe(true)
    expect(isHttpsIp('http://100.72.84.124:8765')).toBe(false)
    expect(isHttpsIp('https://mac.tail1234.ts.net')).toBe(false)
  })

  it("propone l'indirizzo della tailnet al posto di IP e indirizzi locali", () => {
    const tailnet = 'https://mac.tail1234.ts.net'
    expect(preferredOrigin('https://100.72.84.124', 'http://127.0.0.1:8765', tailnet)).toBe(tailnet)
    expect(preferredOrigin('', 'http://127.0.0.1:8765', tailnet)).toBe(tailnet)
    expect(preferredOrigin('http://mac.local:8765', 'http://127.0.0.1:8765', tailnet)).toBe('http://mac.local:8765')
    expect(preferredOrigin('', 'https://altro.tail1234.ts.net', tailnet)).toBe('https://altro.tail1234.ts.net')
    expect(preferredOrigin('', 'http://127.0.0.1:8765', null)).toBe('')
  })
})
