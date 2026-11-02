import { CSRF_COOKIE, CSRF_HEADER, readCookie } from '@/api/client'

/**
 * Inoltra in api.log gli errori e gli avvisi della console della web app (console.error,
 * console.warn, errori e promesse rifiutate non gestiti): nella finestra di RT gli strumenti
 * per sviluppatori non si aprono, e senza questo un errore del frontend non lascia traccia.
 * Lo stesso messaggio parte una volta al minuto, e al massimo MAX_PER_PAGE volte per pagina.
 */
const ENDPOINT = '/api/v1/system/client-log'
const REPEAT_MS = 60_000
const MAX_PER_PAGE = 100
// Rumore noto dei browser, non errori di RT.
const IGNORED = [/ResizeObserver loop/i]

type Level = 'error' | 'warn'

const lastSent = new Map<string, number>()
let sentCount = 0
let sending = false
let installed = false

function describe(value: unknown): { message: string; stack: string } {
  if (value instanceof Error) return { message: `${value.name}: ${value.message}`, stack: value.stack ?? '' }
  if (typeof value === 'string') return { message: value, stack: '' }
  try {
    return { message: JSON.stringify(value) ?? String(value), stack: '' }
  } catch {
    return { message: String(value), stack: '' }
  }
}

function joinArgs(args: unknown[]): { message: string; stack: string } {
  const parts = args.map(describe)
  return {
    message: parts.map((p) => p.message).join(' '),
    stack: parts.find((p) => p.stack)?.stack ?? '',
  }
}

export function reportClientLog(level: Level, message: string, stack = ''): void {
  const text = message.trim()
  if (!text || sending || IGNORED.some((re) => re.test(text))) return
  const key = `${level}:${text}`
  const now = Date.now()
  if ((lastSent.get(key) ?? -Infinity) > now - REPEAT_MS || sentCount >= MAX_PER_PAGE) return
  lastSent.set(key, now)
  sentCount += 1
  sending = true
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const csrf = readCookie(CSRF_COOKIE)
    if (csrf) headers[CSRF_HEADER] = csrf
    void fetch(ENDPOINT, {
      method: 'POST',
      credentials: 'same-origin',
      keepalive: true,
      headers,
      body: JSON.stringify({
        level,
        message: text.slice(0, 2000),
        page: `${window.location.pathname}${window.location.search}`.slice(0, 300),
        stack: stack.slice(0, 4000),
      }),
    }).catch(() => undefined)
  } catch {
    // Il registro non deve mai rompere la pagina.
  } finally {
    sending = false
  }
}

export function installClientLog(): void {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('error', (event) => {
    const { message, stack } = event.error ? describe(event.error) : { message: event.message, stack: '' }
    const where = event.filename ? ` (${event.filename}:${event.lineno}:${event.colno})` : ''
    reportClientLog('error', `${message}${where}`, stack)
  })
  window.addEventListener('unhandledrejection', (event) => {
    const { message, stack } = describe(event.reason)
    reportClientLog('error', `Promessa rifiutata: ${message}`, stack)
  })
  for (const level of ['error', 'warn'] as const) {
    const original = console[level].bind(console)
    console[level] = (...args: unknown[]) => {
      original(...args)
      const { message, stack } = joinArgs(args)
      reportClientLog(level, message, stack)
    }
  }
}

/** Solo per i test. */
export function resetClientLogForTests(): void {
  lastSent.clear()
  sentCount = 0
}
