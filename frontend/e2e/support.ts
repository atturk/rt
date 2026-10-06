import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test as base, type APIRequestContext, type Locator, type Page } from '@playwright/test'

type ServerState = { base_url: string; token: string; lessons_root: string; searxng_url: string }

/** Ogni e2e lascia le preferenze del server come le ha trovate, anche se fallisce. */
export const test = base.extend<{ restorePreferences: void }>({
  restorePreferences: [async ({ page, request }, use) => {
    const previous = await apiGet<Record<string, unknown>>(request, '/preferences')
    await use()
    // Ferma anche i salvataggi differiti della pagina prima del ripristino.
    if (!page.isClosed()) await page.goto('about:blank')
    const current = await apiGet<Record<string, unknown>>(request, '/preferences')
    for (const key of new Set([...Object.keys(previous), ...Object.keys(current)])) {
      if (JSON.stringify(previous[key]) === JSON.stringify(current[key])) continue
      const path = `/api/v1/preferences/${encodeURIComponent(key)}`
      const response = Object.hasOwn(previous, key)
        ? await request.put(path, { headers: { ...authHeaders(), 'Content-Type': 'application/json' }, data: JSON.stringify(previous[key]) })
        : await request.delete(path, { headers: authHeaders() })
      expect(response.ok(), `Ripristino della preferenza ${key}`).toBeTruthy()
    }
  }, { auto: true, timeout: 30_000 }],
})

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

/**
 * Pagina della lezione: fasi, job, costi e scaletta stanno nel pannello laterale Dettagli
 * (design 4.2). Lo apre se non è già aperto (la scelta resta nel browser).
 */
export async function openLessonDetails(page: Page) {
  const panel = page.locator('[data-testid=lesson-panel][data-view=dettagli]')
  await expect(page.getByTestId('lesson-actions')).toBeVisible()
  if (!(await panel.isVisible())) await page.getByTestId('lesson-actions').getByRole('button', { name: 'Dettagli' }).click()
  await expect(panel).toBeVisible()
  return panel
}

/** Voce del menu Esporta dell'intestazione della lezione. */
export async function exportItem(page: Page, name: string | RegExp) {
  await page.getByTestId('lesson-actions').getByRole('button', { name: 'Esporta' }).click()
  return page.getByRole('menu', { name: 'Esporta' }).getByRole('menuitem', { name })
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

/** Il documento della lezione è un editor (CodeMirror): disegna solo le righe vicine alla vista. Scorre finché l'elemento c'è. */
export async function scrollDocumentTo(page: Page, target: Locator) {
  await expect
    .poll(async () => {
      if ((await target.count()) > 0) return true
      await page.getByTestId('lesson-document').evaluate((el) => {
        // il primo antenato che scorre (la pagina o il contenitore principale)
        let node: HTMLElement | null = el as HTMLElement
        while (node && node.scrollHeight <= node.clientHeight) node = node.parentElement
        ;(node ?? document.scrollingElement)?.scrollBy(0, 600)
      })
      return false
    }, { timeout: 15_000 })
    .toBe(true)
  await target.first().scrollIntoViewIfNeeded()
}

/** Senza approvazione automatica della scaletta (B9): i test approvano o chiedono modifiche a mano. */
export async function disableOutlineTimer(request: APIRequestContext) {
  const res = await request.put('/api/v1/settings/preferences', { headers: authHeaders(), data: { secondi_approvazione: 0 } })
  expect(res.ok(), await res.text()).toBeTruthy()
}

/** Importazione dell'audio dall'API, come il popup Nuova lezione; ritorna l'id del job. */
export async function importAudioApi(
  request: APIRequestContext,
  audio: string,
  fields: { materia: string; argomenti: string; date: string; run: boolean; withReview?: boolean },
) {
  const res = await request.post('/api/v1/lessons', {
    headers: authHeaders(),
    multipart: {
      audio: { name: 'demo_lecture.wav', mimeType: 'audio/wav', buffer: readFileSync(audio) },
      date: fields.date,
      materia: fields.materia,
      argomenti: fields.argomenti,
      docente: '',
      ora: '',
      run: String(fields.run),
      mock: 'true',
      auto_accept: 'false',
      with_review: String(fields.withReview ?? fields.run),
    },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return ((await res.json()) as { job_id: string }).job_id
}

/** Job della lezione nel pannello Dettagli: l'elenco si apre con "ultimi 5". */
export async function lessonJobs(page: Page) {
  const details = await openLessonDetails(page)
  const jobs = page.getByTestId('jobs-panel')
  if (!(await jobs.isVisible())) await details.getByRole('button', { name: /^ultimi 5/ }).click()
  await expect(jobs).toBeVisible()
  return jobs
}

/** Riesegue una fase dal menu ⋯ della sua riga nel pannello Dettagli. */
export async function runPhase(page: Page, label: string) {
  const details = await openLessonDetails(page)
  await details.getByRole('button', { name: `Azioni su ${label}` }).click()
  await page.getByRole('menu', { name: `Azioni su ${label}` }).getByRole('menuitem', { name: 'Riesegui', exact: true }).click()
}
