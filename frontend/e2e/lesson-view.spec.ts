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

type Warning = { code: string; message: string }
type Phases = { phases: { phase: string; status: string; warnings?: Warning[] }[] }

test('Documento con revisione non aggiornata: dialogo con gli avvisi, conferma e documento valido dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'ANATOMIA')
  const before = await apiGet<Phases>(page.request, `/lessons/${id}/phases`)
  expect(before.phases.find((p) => p.phase === 'review')?.status).toBe('STALE')
  const warnings = before.phases.find((p) => p.phase === 'build')?.warnings ?? []
  expect(warnings.map((w) => w.code)).toEqual(['review_stale', 'pending_issues'])

  await page.goto(`/lezioni/${id}`)
  const build = page.locator('[data-phase-row="build"]')
  await expect(build).toHaveAttribute('data-status', 'MISSING')
  await expect(build.getByTestId('build-warnings')).toContainText('10 issue ancora da valutare')

  // Annulla: nessun job parte
  await page.getByRole('button', { name: 'Esegui Documento' }).click()
  const dialog = page.getByRole('dialog', { name: 'Creare il documento finale?' })
  await expect(dialog).toBeVisible()
  for (const w of warnings) await expect(dialog.getByTestId('build-confirm-warnings')).toContainText(w.message)
  await expect(dialog).toContainText('Revisione non aggiornata')
  await dialog.getByRole('button', { name: 'Annulla' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('[data-testid=jobs-panel] [data-job-state]')).toHaveCount(0)

  // Conferma: il documento finale viene creato anche con la revisione non aggiornata
  await page.getByRole('button', { name: 'Esegui Documento' }).click()
  await dialog.getByRole('button', { name: 'Crea il documento comunque' }).click()
  await expect(page.getByTestId('jobs-panel').locator('[data-job-state]').first()).toHaveAttribute('data-job-state', 'succeeded', {
    timeout: 45_000,
  })
  await expect(build).toHaveAttribute('data-status', 'VALID')

  await page.reload()
  await expect(build).toHaveAttribute('data-status', 'VALID')
  await expect(page.locator('[data-phase-row="review"]')).toHaveAttribute('data-status', 'STALE')
  const after = await apiGet<Phases>(page.request, `/lessons/${id}/phases`)
  expect(after.phases.find((p) => p.phase === 'build')?.status).toBe('VALID')
  const doc = await apiGet<{ final: boolean }>(page.request, `/lessons/${id}/document`)
  expect(doc.final).toBe(true)
})

test('intestazione: Recall, Immagini e download sempre nello stesso posto, disabilitati con il motivo', async ({ page }) => {
  await loginViaLink(page)
  const labels = ['Recall', 'Immagini', 'Markdown', 'Tutti i dati (zip)']

  // Lezione senza rielaborazione: le quattro azioni ci sono, disabilitate con il motivo
  const setupOnly = await lessonId(page, 'FISIOLOGIA')
  await page.goto(`/lezioni/${setupOnly}`)
  const actions = page.getByTestId('lesson-actions')
  await expect(actions.locator('a, button')).toHaveText(labels)
  for (const label of labels) {
    const slot = actions.locator(`[data-action-disabled="${label}"]`)
    await expect(slot.getByRole('button', { name: label })).toBeDisabled()
    await expect(slot).toHaveAttribute('title', /rielaborazione/)
  }

  // Dopo il rewrite, senza documento finale: tutte disponibili; il Markdown è l'anteprima
  const reviewed = await lessonId(page, 'FARMACOLOGIA')
  const phases = await apiGet<Phases>(page.request, `/lessons/${reviewed}/phases`)
  expect(phases.phases.find((p) => p.phase === 'build')?.status).toBe('MISSING')
  await page.goto(`/lezioni/${reviewed}`)
  await expect(actions.locator('a, button')).toHaveText(labels)
  await expect(actions.locator('[data-action-disabled]')).toHaveCount(0)
  await expect(page.getByText(/Anteprima dalla bozza/)).toBeVisible()
  const download = page.waitForEvent('download')
  await actions.getByRole('link', { name: 'Markdown' }).click()
  expect((await download).suggestedFilename()).toMatch(/\(anteprima\)\.md$/)

  await actions.getByRole('link', { name: 'Recall' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${reviewed}/recall$`))
  await expect(page.getByText('La lezione non ha ancora una rielaborazione valida')).toHaveCount(0)
  await page.goto(`/lezioni/${reviewed}`)
  await actions.getByRole('link', { name: 'Immagini' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${reviewed}/immagini$`))
  await expect(page.getByRole('button', { name: 'Aggiungi le immagini' })).toBeVisible()
})
