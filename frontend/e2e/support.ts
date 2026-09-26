import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

type ServerState = { base_url: string; token: string; lessons_root: string }

export function serverState(): ServerState {
  const file = fileURLToPath(new URL('./.state/server.json', import.meta.url))
  return JSON.parse(readFileSync(file, 'utf-8')) as ServerState
}

/** Client dell'API con il token: serve a rileggere dal backend quello che la pagina mostra. */
export function authHeaders() {
  return { Authorization: `Bearer ${serverState().token}` }
}

export async function apiGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`/api/v1${path}`, { headers: authHeaders() })
  expect(res.ok(), `GET ${path} -> ${res.status()}`).toBeTruthy()
  return (await res.json()) as T
}

/** Link monouso come quello che apre 'rt web'. */
export async function loginLink(request: APIRequestContext): Promise<string> {
  const res = await request.post('/api/v1/auth/login-link', { headers: authHeaders() })
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as { url: string }).url
}

export async function loginViaLink(page: Page) {
  await page.goto(await loginLink(page.request))
  await expect(page).toHaveURL(/\/$/)
}
