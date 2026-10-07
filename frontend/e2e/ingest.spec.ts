import { fileURLToPath } from 'node:url'
import { expect, type Page } from '@playwright/test'

import { test, apiGet, disableOutlineTimer, importAudioApi, loginViaLink } from './support'

// RT4-F4: importazione con upload, job con eventi live (SSE), approvazione della scaletta.
// Il worker di scripts/e2e_server.py esegue davvero i job; la modalità prova (mock) evita
// trascrizione e modelli, come 'rt run --mock'.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; type: string; state: string; lesson_id: number | null; decision: { kind: string } | null }
type JobEvent = { id: number; type: string }
type Outline = { approved: boolean; macro_sections: { units: unknown[] }[] }
type Lesson = { id: number; materia: string; argomenti: string; pending_issues: number; state: string | null }

/** Importazione dall'API (la pagina Importa non c'è più) e pagina del job che la segue. */
async function importAudio(page: Page, fields: { materia: string; argomenti: string; date: string; run: boolean }) {
  await disableOutlineTimer(page.request)
  const jobId = await importAudioApi(page.request, AUDIO, fields)
  await page.goto(`/job/${jobId}`)
  return jobId
}

function jobCard(page: Page) {
  return page.getByTestId('job-live').first()
}

async function eventCount(page: Page, jobId: string) {
  return (await apiGet<JobEvent[]>(page.request, `/jobs/${jobId}/events/list`)).length
}

test('importa un audio, segue gli eventi, approva la scaletta e arriva alla review', async ({ page }) => {
  test.setTimeout(4 * LONG)
  await loginViaLink(page)
  await expect(page.getByTestId('worker-warning')).toHaveCount(0)
  const jobId = await importAudio(page, { materia: 'ANATOMIA', argomenti: 'Il cuore', date: '2026-09-19', run: true })

  // La pipeline si ferma sulla scaletta: lo stream mostra fasi e decisione, poi si chiude.
  await expect(jobCard(page)).toHaveAttribute('data-state', 'waiting_for_decision', { timeout: LONG })
  const log = page.getByRole('log', { name: 'Eventi del job' })
  await expect(log.locator('[data-event-type=phase_started]').first()).toBeVisible()
  await expect(log.locator('[data-event-type=decision_required]')).toHaveCount(1)
  await expect(page.getByTestId('job-decision')).toContainText('approvare la scaletta')
  const job = await apiGet<Job>(page.request, `/jobs/${jobId}`)
  expect(job.state).toBe('waiting_for_decision')
  expect(job.decision?.kind).toBe('outline_approval')
  const lesson = await apiGet<Lesson>(page.request, `/lessons/${job.lesson_id}`)
  expect(lesson.materia).toBe('ANATOMIA')

  // Dopo la ricarica lo stream riparte e mostra tutti gli eventi salvati.
  await page.reload()
  await expect(log.locator('li[data-event-type]')).toHaveCount(await eventCount(page, jobId))

  // La lezione mostra la scaletta da approvare al posto del testo (C4).
  await page.goto(`/lezioni/${job.lesson_id}`)
  const approval = page.getByTestId('outline-approval')
  await expect(approval).toContainText('Scaletta da approvare')
  const outline = await apiGet<Outline>(page.request, `/lessons/${job.lesson_id}/outline`)
  const scaletta = page.getByLabel('Scaletta della lezione')
  await expect(scaletta.getByRole('heading', { level: 2 })).toHaveCount(outline.macro_sections.length)
  await expect(scaletta.getByRole('heading', { level: 3 })).toHaveCount(outline.macro_sections.flatMap((m) => m.units).length)

  await approval.getByRole('button', { name: /^Approva/ }).click()
  await expect.poll(async () => (await apiGet<Outline>(page.request, `/lessons/${job.lesson_id}/outline`)).approved).toBe(true)
  await page.reload()
  await expect(page.getByTestId('outline-approval')).toHaveCount(0)

  // Lo stesso job riparte: la pagina lo segue fino alla review e la ricarica a metà non perde eventi.
  await page.goto(`/job/${jobId}`)
  await page.reload()
  await expect(log.locator('[data-event-type=job_resumed]')).toHaveCount(1, { timeout: LONG })
  await expect(jobCard(page)).toHaveAttribute('data-state', 'waiting_for_decision', { timeout: LONG })
  await expect(page.getByTestId('job-decision')).toContainText('valutare le issue della review')
  await expect(log.locator('li[data-event-type]')).toHaveCount(await eventCount(page, jobId))
  const reviewing = await apiGet<Job>(page.request, `/jobs/${jobId}`)
  expect(reviewing.decision?.kind).toBe('science_issue')
  expect((await apiGet<Lesson>(page.request, `/lessons/${job.lesson_id}`)).pending_issues).toBeGreaterThan(0)

  // Il pannello dei job elenca il job con la decisione da prendere.
  await page.goto('/job')
  const row = page.locator(`[data-testid=job-row][data-job-id="${jobId}"]`)
  await expect(row).toHaveAttribute('data-state', 'waiting_for_decision')
  await expect(row).toContainText('valutare le issue della review')
  await expect(page.getByTestId('jobs-indicator')).toContainText(/in attesa di una tua decisione/)
})

test('importazione senza pipeline: solo trascrizione, come rt setup', async ({ page }) => {
  test.setTimeout(2 * LONG)
  await loginViaLink(page)
  const jobId = await importAudio(page, { materia: 'ISTOLOGIA', argomenti: 'Epiteli', date: '2026-09-20', run: false })
  await expect(jobCard(page)).toHaveAttribute('data-state', 'succeeded', { timeout: LONG })
  const job = await apiGet<Job>(page.request, `/jobs/${jobId}`)
  expect(job.type).toBe('ingest_audio')
  expect(job.lesson_id).not.toBeNull()
  await page.reload()
  await expect(jobCard(page)).toHaveAttribute('data-state', 'succeeded')
  await page.goto(`/lezioni/${job.lesson_id}`)
  const lesson = await apiGet<Lesson>(page.request, `/lessons/${job.lesson_id}`)
  expect(lesson.materia).toBe('ISTOLOGIA')
  expect(lesson.argomenti).toContain('Epiteli')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('errori leggibili su formato e campi mancanti', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('button', { name: 'Nuova lezione' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles({ name: 'appunti.txt', mimeType: 'text/plain', buffer: Buffer.from('ciao') })
  await dialog.getByLabel('Materia').fill('X')
  await dialog.getByRole('button', { name: 'Avvia' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Formato non supportato: appunti.txt')
  await expect(dialog).toBeVisible()
})

test('richiesta di modifiche alla scaletta e annullamento del job in attesa', async ({ page }) => {
  test.setTimeout(3 * LONG)
  await loginViaLink(page)
  const jobId = await importAudio(page, { materia: 'GENETICA', argomenti: 'Mendel', date: '2026-09-21', run: true })
  await expect(jobCard(page)).toHaveAttribute('data-state', 'waiting_for_decision', { timeout: LONG })
  const { lesson_id: lessonId } = await apiGet<Job>(page.request, `/jobs/${jobId}`)

  await page.goto(`/lezioni/${lessonId}`)
  const approval = page.getByTestId('outline-approval')
  await approval.getByLabel('Oppure chiedi modifiche').fill('Dividi la prima sezione in due unità')
  await approval.getByRole('button', { name: 'Rigenera con queste modifiche' }).click()
  await expect.poll(async () => (await apiGet<Job[]>(page.request, `/jobs?lesson_id=${lessonId}`)).find((j) => j.type === 'outline_revision')?.state, { timeout: LONG }).toBe('succeeded')
  await page.reload()
  await expect(page.getByTestId('outline-approval')).toBeVisible()
  expect((await apiGet<Outline>(page.request, `/lessons/${lessonId}/outline`)).approved).toBe(false)

  // La pipeline in attesa si annulla dalla pagina del job e resta annullata dopo la ricarica.
  await page.goto(`/job/${jobId}`)
  await page.getByRole('button', { name: 'Annulla job' }).click()
  await expect(jobCard(page)).toHaveAttribute('data-state', 'cancelled')
  await page.reload()
  await expect(jobCard(page)).toHaveAttribute('data-state', 'cancelled')
  expect((await apiGet<Job>(page.request, `/jobs/${jobId}`)).state).toBe('cancelled')
  await page.goto('/job?stato=cancelled')
  await expect(page.locator(`[data-testid=job-row][data-job-id="${jobId}"]`)).toBeVisible()
})
