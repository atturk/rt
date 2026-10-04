/** Accesso da un altro dispositivo (es. iPhone): il link monouso creato dall'API porta
 * l'indirizzo con cui il Mac ha aperto RT, spesso 127.0.0.1. Qui si rimette il codice
 * sull'indirizzo che l'altro dispositivo raggiunge (Tailscale o rete locale). */

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

export const DEVICE_ORIGIN_KEY = 'rt-device-origin'

export function isLoopback(origin: string): boolean {
  try {
    return LOOPBACK_HOSTS.has(new URL(origin).hostname)
  } catch {
    return false
  }
}

/** "nome-mac.tailnet.ts.net" o "https://…/" → "https://nome-mac.tailnet.ts.net"; null se non è un indirizzo. */
export function normalizeOrigin(value: string): string | null {
  const text = value.trim()
  if (!text) return null
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    return url.origin
  } catch {
    return null
  }
}

/** Il link per l'altro dispositivo: stesso codice monouso, indirizzo scelto. */
export function deviceLoginUrl(apiUrl: string, origin: string): string | null {
  try {
    const code = new URL(apiUrl).searchParams.get('code')
    return code ? `${origin}/login?code=${encodeURIComponent(code)}` : null
  } catch {
    return null
  }
}

export function readDeviceOrigin(): string {
  try {
    return localStorage.getItem(DEVICE_ORIGIN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveDeviceOrigin(origin: string): void {
  try {
    localStorage.setItem(DEVICE_ORIGIN_KEY, origin)
  } catch {
    /* storage may be disabled */
  }
}
