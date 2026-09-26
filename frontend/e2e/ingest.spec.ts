import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// RT4-F4: importazione con upload, job con eventi live (SSE), approvazione della scaletta.
// Il worker di scripts/e2e_server.py esegue davvero i job; la modalità prova (mock) evita
// trascrizione e modelli, come 'rt run --mock'.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; type: string; state: string; lesson_id: number | null; decision: { kind: string } | null }
type JobEvent = { id: number; type: string }
type Outline = { approved: boolean; macro_sections: { units: unknown[] }[] }
type Lesson = { id: number; materia: string; argomenti: string; pending_issues: number; state: string | null }

async function importAudio(page: Page, fields: { materia: string; argomenti: string; date: string; run: boolean }) {
  await page.goto('/importa')
  await page.getByLabel('File audio', { exact: true }).setInputFiles(AUDIO)
  await page.getByLabel('Data', { exact: true }).fill(fields.date)
  await page.getByLabel('Materia', { exact: true }).fill(fields.materia)
  await page.getByLabel('Argomenti', { exact: true }).fill(fields.argomenti)
  await page.getByLabel('Avvia subito la pipeline').setChecked(fields.run)
  await page.getByText('Opzioni avanzate').click()
  await page.getByLabel('Modalità prova (mock)').check()
  await page.getByRole('button', { name: 'Importa' }).click()
  await expect(page).toHaveURL(/\/job\/[0-9a-f-]+$/)
  return page.url().split('/job/')[1]
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

  // La lezione dice che serve la tua approvazione e porta alla scaletta.
  await page.goto(`/lezioni/${job.lesson_id}`)
  await expect(page.getByTestId('lesson-waiting')).toContainText('Serve la tua approvazione')
  await page.getByTestId('lesson-waiting').getByRole('link', { name: 'Rivedi la scaletta' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${job.lesson_id}/outline$`))
  await expect(page.getByTestId('outline-waiting')).toBeVisible()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'false')
  const outline = await apiGet<Outline>(page.request, `/lessons/${job.lesson_id}/outline`)
  await expect(page.getByTestId('outline-macro')).toHaveCount(outline.macro_sections.length)
  await expect(page.getByTestId('outline-unit')).toHaveCount(outline.macro_sections.flatMap((m) => m.units).length)

  await page.getByRole('button', { name: 'Approva la scaletta' }).click()
  await expect(page.getByTestId('pipeline-resumed')).toBeVisible()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'true')
  expect((await apiGet<Outline>(page.request, `/lessons/${job.lesson_id}/outline`)).approved).toBe(true)
  await page.reload()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'true')
  await expect(page.getByTestId('outline-waiting')).toHaveCount(0)

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
  await page.getByRole('link', { name: 'Apri la lezione' }).last().click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${job.lesson_id}$`))
  const lesson = await apiGet<Lesson>(page.request, `/lessons/${job.lesson_id}`)
  expect(lesson.materia).toBe('ISTOLOGIA')
  expect(lesson.argomenti).toContain('Epiteli')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('errori leggibili su formato e campi mancanti', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/importa')
  await page.getByLabel('File audio', { exact: true }).setInputFiles({ name: 'appunti.txt', mimeType: 'text/plain', buffer: Buffer.from('ciao') })
  await page.getByLabel('Materia', { exact: true }).fill('X')
  await page.getByRole('button', { name: 'Importa' }).click()
  await expect(page.getByRole('alert')).toContainText('Formato non supportato: appunti.txt')
  await expect(page).toHaveURL(/\/importa$/)
})

test('richiesta di modifiche alla scaletta e annullamento del job in attesa', async ({ page }) => {
  test.setTimeout(3 * LONG)
  await loginViaLink(page)
  const jobId = await importAudio(page, { materia: 'GENETICA', argomenti: 'Mendel', date: '2026-09-21', run: true })
  await expect(jobCard(page)).toHaveAttribute('data-state', 'waiting_for_decision', { timeout: LONG })
  const { lesson_id: lessonId } = await apiGet<Job>(page.request, `/jobs/${jobId}`)

  await page.goto(`/lezioni/${lessonId}/outline`)
  await page.getByLabel('Richiedi modifiche', { exact: true }).fill('Dividi la prima sezione in due unità')
  await page.getByLabel('Modalità prova (mock)').check()
  await page.getByRole('button', { name: 'Rigenera con il feedback' }).click()
  const revision = page.getByTestId('job-live')
  await expect(revision).toHaveAttribute('data-state', 'succeeded', { timeout: LONG })
  const revisionJobs = await apiGet<Job[]>(page.request, `/jobs?lesson_id=${lessonId}`)
  expect(revisionJobs.find((j) => j.type === 'outline_revision')?.state).toBe('succeeded')
  await page.reload()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'false')
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
