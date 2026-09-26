import createClient, { type Middleware } from 'openapi-fetch'

import type { components, paths } from './schema'

export type Schemas = components['schemas']

/** Errore uniforme dell'API: {"error": {"code", "message", "details"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export const CSRF_COOKIE = 'rt_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export function readCookie(name: string): string | undefined {
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const item = part.trim()
    if (item.startsWith(prefix)) return decodeURIComponent(item.slice(prefix.length))
  }
  return undefined
}

/** Ripete il cookie rt_csrf nell'header X-CSRF-Token per le scritture (double submit). */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method.toUpperCase())) {
      const csrf = readCookie(CSRF_COOKIE)
      if (csrf) request.headers.set(CSRF_HEADER, csrf)
    }
    return request
  },
}

/** Stessa origine: in produzione FastAPI serve la SPA, in sviluppo il proxy di Vite. */
export const api = createClient<paths>({ baseUrl: '', credentials: 'same-origin' })
api.use(csrfMiddleware)

export function toApiError(status: number, body: unknown): ApiError {
  const err = (body as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error
  if (err?.code) return new ApiError(status, err.code, err.message ?? 'Errore', err.details)
  if (status === 0) return new ApiError(0, 'network_error', 'API non raggiungibile: RT è avviato?')
  return new ApiError(status, 'http_error', `Errore ${status}`)
}

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Restituisce i dati o solleva ApiError: da usare nelle queryFn e mutationFn. */
export async function unwrap<T>(promise: Promise<Result<T>>): Promise<T> {
  let result: Result<T>
  try {
    result = await promise
  } catch {
    throw toApiError(0, undefined)
  }
  if (result.error !== undefined || !result.response.ok) throw toApiError(result.response.status, result.error)
  return result.data as T
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Errore inatteso.'
}
