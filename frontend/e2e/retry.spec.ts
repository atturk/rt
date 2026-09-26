import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// RT4-FA1: un job fallito si riprova dalla web. Il job in mock fallisce apposta
// (mock_fail_once: la review risponde fuori schema, come openrouter/free nel test reale); con
// "Riprova" nasce un job nuovo collegato al vecchio, che riparte dalla fase fallita: le fasi
// già valide si saltano e il job arriva in fondo. Tutto riletto dall'API, anche dopo la ricarica.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; state: string; lesson_id: number | null; error: string | null; retry_of: string | null; retried_by: string | null }
type JobEvent = { id: number; type: string; payload: Record<string, unknown> }
type PhaseReport = { phases: { phase: string; status: string; reason: string }[] }

async function waitJob(page: Page, id: string, states: string[]): Promise<Job> {
  let job: Job | undefined
  await expect
    .poll(async () => (job = await apiGet<Job>(page.request, `/jobs/${id}`)).state, { timeout: LONG })
    .toMatch(new RegExp(`^(${states.join('|')})$`))
  return job!
}

/** Lezione nuova solo per questo test: importazione in mock (senza pipeline) via API. */
async function newLesson(page: Page): Promise<number> {
  const res = await page.request.post('/api/v1/lessons', {
    headers: authHeaders(),
    multipart: {
      audio: { name: 'lezione.wav', mimeType: 'audio/wav', buffer: readFileSync(AUDIO) },
      date: '2026-09-26',
      materia: 'ISTOLOGIA',
      argomenti: 'Epiteli',
      mock: 'true',
      run: 'false',
    },
  })
  expect(res.status()).toBe(202)
  const job = await waitJob(page, ((await res.json()) as { job_id: string }).job_id, ['succeeded'])
  return job.lesson_id!
}

test('un job fallito si riprova: il nuovo job riparte dalla fase fallita e completa', async ({ page }) => {
  test.setTimeout(4 * LONG)
  await loginViaLink(page)
  const lessonId = await newLesson(page)
  const res = await page.request.post(`/api/v1/lessons/${lessonId}/jobs`, {
    headers: authHeaders(),
    data: { type: 'run_pipeline', mock: true, auto_accept: true, rename: false, mock_fail_once: 'review' },
  })
  expect(res.status()).toBe(202)
  const failedId = ((await res.json()) as { job_id: string }).job_id

  // Il job fallisce sulla review con un messaggio leggibile: modello, unità, inizio della risposta.
  await page.goto(`/job/${failedId}`)
  const card = page.getByTestId('job-live')
  await expect(card).toHaveAttribute('data-state', 'failed', { timeout: LONG })
  await expect(page.getByTestId('job-error')).toContainText('Revisione incompleta')
  await expect(page.getByTestId('job-error')).toContainText('«User Safety: safe / Response Safety: safe»')
  const phases = await apiGet<PhaseReport>(page.request, `/lessons/${lessonId}/phases`)
  expect(phases.phases.find((p) => p.phase === 'rewrite')?.status).toBe('VALID')
  expect(phases.phases.find((p) => p.phase === 'review')?.status).not.toBe('VALID')

  // Riprova accanto a "Fallito"
  const retry = card.getByRole('button', { name: 'Riprova' })
  await expect(retry).toBeVisible()
  await retry.click()
  await expect(page).not.toHaveURL(new RegExp(`/job/${failedId}$`))
  const retryId = page.url().split('/job/')[1]
  await expect(page.getByTestId('job-live')).toHaveAttribute('data-state', 'succeeded', { timeout: LONG })
  await expect(page.getByTestId('retry-of')).toHaveAttribute('href', `/job/${failedId}`)

  // Ripartito dalla fase fallita: scaletta e rielaborazione già valide, review e documento rifatti.
  const events = await apiGet<JobEvent[]>(page.request, `/jobs/${retryId}/events/list`)
  const completed = Object.fromEntries(
    events.filter((e) => e.type === 'phase_completed').map((e) => [String(e.payload.phase), e.payload.skipped]),
  )
  expect(completed).toMatchObject({ outline: true, rewrite: true, review: false, build: false })
  const log = page.getByRole('log', { name: 'Eventi del job' })
  await expect(log).toContainText('Rielaborazione: già aggiornata')
  await expect(log).toContainText('Revisione: completata')

  // Dopo la ricarica tutto viene dall'API: collegamenti in entrambe le direzioni.
  await page.reload()
  await expect(page.getByTestId('job-live')).toHaveAttribute('data-state', 'succeeded')
  await expect(page.getByTestId('retry-of')).toBeVisible()
  const [oldJob, newJob] = await Promise.all([apiGet<Job>(page.request, `/jobs/${failedId}`), apiGet<Job>(page.request, `/jobs/${retryId}`)])
  expect(newJob.retry_of).toBe(failedId)
  expect(oldJob.retried_by).toBe(retryId)
  const after = await apiGet<PhaseReport>(page.request, `/lessons/${lessonId}/phases`)
  expect(after.phases.every((p) => p.status === 'VALID')).toBeTruthy()

  await page.goto(`/job/${failedId}`)
  await expect(page.getByTestId('job-live')).toHaveAttribute('data-state', 'failed')
  await expect(page.getByTestId('retried-by').getByRole('link', { name: 'Segui il nuovo tentativo' })).toHaveAttribute('href', `/job/${retryId}`)
  await expect(page.getByTestId('job-live').getByRole('button', { name: 'Riprova' })).toHaveCount(0)

  // Pannello job della lezione: il fallito punta al nuovo tentativo, niente più Riprova.
  await page.goto(`/lezioni/${lessonId}`)
  const panel = page.getByTestId('jobs-panel')
  await expect(panel.locator(`[data-job-id="${failedId}"]`)).toHaveAttribute('data-job-state', 'failed')
  await expect(panel.locator(`[data-job-id="${failedId}"]`).getByRole('link', { name: 'Nuovo tentativo' })).toBeVisible()
  await expect(panel.locator(`[data-job-id="${retryId}"]`)).toHaveAttribute('data-job-state', 'succeeded')
})

test('Riprova nel pannello job della lezione', async ({ page }) => {
  test.setTimeout(3 * LONG)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=ISTOLOGIA')
  const res = await page.request.post(`/api/v1/lessons/${lesson.id}/jobs`, {
    headers: authHeaders(),
    data: { type: 'run_phase', phase: 'rewrite', force: true, mock: true, mock_fail_once: 'rewrite' },
  })
  const failedId = ((await res.json()) as { job_id: string }).job_id
  await waitJob(page, failedId, ['failed'])
  await page.goto(`/lezioni/${lesson.id}`)
  const row = page.getByTestId('jobs-panel').locator(`[data-job-id="${failedId}"]`)
  await expect(row).toContainText('Rielaborazione incompleta')
  await row.getByRole('button', { name: 'Riprova' }).click()
  await expect(row.getByRole('link', { name: 'Nuovo tentativo' })).toBeVisible()
  const old = await apiGet<Job>(page.request, `/jobs/${failedId}`)
  const retried = await waitJob(page, old.retried_by!, ['succeeded'])
  expect(retried.retry_of).toBe(failedId)
  await page.reload()
  await expect(page.getByTestId('jobs-panel').locator(`[data-job-id="${retried.id}"]`)).toHaveAttribute('data-job-state', 'succeeded')
})
