import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

type ServerState = { base_url: string; token: string; lessons_root: string; searxng_url: string }

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

/** PDF di una pagina, abbastanza valido per PyMuPDF. */
export function tinyPdf(): Buffer {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 180] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  const stream = 'BT /F1 24 Tf 40 90 Td (Slide di prova: lipidi) Tj ET'
  objects[3] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(pdf.length)
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(pdf, 'latin1')
}
