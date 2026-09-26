import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; materia: string }
type PhaseReport = { phases: { phase: string; status: string; reason: string }[] }
type Detail = { outline_approved: boolean; cost_usd: number | null }

async function lessonId(page: Page, materia: string) {
  const [lesson] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return lesson.id
}

test('la vista lezione mostra documento, fasi, validazioni, costi e download', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)
  const report = await apiGet<PhaseReport>(page.request, `/lessons/${id}/phases`)
  const detail = await apiGet<Detail>(page.request, `/lessons/${id}`)

  const doc = page.getByTestId('lesson-document')
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(doc.locator('h2').first()).toBeVisible()
  await expect(doc.locator('[data-unit-id]').first()).toBeVisible()

  for (const row of report.phases) {
    const li = page.locator(`[data-phase-row="${row.phase}"]`)
    await expect(li).toHaveAttribute('data-status', row.status)
    await expect(li).toContainText(row.reason)
  }
  await expect(page.getByTestId('outline-approved')).toHaveText(detail.outline_approved ? 'sì' : 'no')
  await expect(page.getByTestId('validation-outline')).toContainText('valida')
  await expect(page.getByTestId('cost-panel')).toContainText('Scaletta')

  const markdown = page.getByRole('link', { name: 'Markdown' })
  await expect(markdown).toHaveAttribute('href', `/api/v1/lessons/${id}/export?format=markdown`)
  const download = page.waitForEvent('download')
  await markdown.click()
  expect((await download).suggestedFilename()).toMatch(/\.md$/)
})

test('il clic su un timecode sposta l\'audio e evidenzia l\'unità', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)
  await expect(page.getByTestId('audio-player')).toBeVisible()
  const timecode = page.getByTestId('lesson-document').locator('.rt-timecode').first()
  await expect(timecode).toHaveText('00:02')
  await page.locator('audio').evaluate((a: HTMLAudioElement) => (a.muted = true))
  await timecode.click()
  await expect
    .poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.currentTime))
    .toBeGreaterThanOrEqual(2)
  await expect(page.getByTestId('lesson-document')).toHaveAttribute('data-active-unit', /.+/)
  await expect(page.locator('.rt-unit-active').first()).toBeVisible()
})

test('avvio di una fase: il job gira sul worker e lo stato resta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FISIOLOGIA')
  await page.goto(`/lezioni/${id}`)
  const prepare = page.locator('[data-phase-row="prepare"]')
  await expect(prepare).not.toHaveAttribute('data-status', 'VALID')

  await page.getByRole('button', { name: 'Esegui Preparazione' }).click()
  await expect(page.getByTestId('jobs-panel')).toContainText('Preparazione')
  await expect(page.getByTestId('jobs-panel').locator('[data-job-state]').first()).toHaveAttribute('data-job-state', 'succeeded', {
    timeout: 45_000,
  })
  await expect(prepare).toHaveAttribute('data-status', 'VALID')

  await page.reload()
  await expect(prepare).toHaveAttribute('data-status', 'VALID')
  const report = await apiGet<PhaseReport>(page.request, `/lessons/${id}/phases`)
  expect(report.phases.find((p) => p.phase === 'prepare')?.status).toBe('VALID')
  await expect(page.getByTestId('jobs-panel')).toContainText('completato')
})

test('esportazione: Markdown finale e zip completo uguali a quelli dell\'API', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)

  let download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Markdown' }).click()
  const markdown = readFileSync((await (await download).path())!, 'utf-8')
  const fromApi = await page.request.get(`/api/v1/lessons/${id}/export?format=markdown`, { headers: authHeaders() })
  expect(markdown).toBe(await fromApi.text())
  expect(markdown).toContain('# ')

  download = page.waitForEvent('download')
  await page.getByRole('link', { name: /zip/i }).click()
  const zip = readFileSync((await (await download).path())!)
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  expect(zip.subarray(0, 2).toString()).toBe('PK')
  expect(zip.includes(Buffer.from('info.yaml'))).toBeTruthy()
})
