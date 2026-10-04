import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, exportItem, loginViaLink, openLessonDetails, lessonJobs, runPhase } from './support'

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
  await expect(doc.locator('.cm-atomic-h2').first()).toBeVisible()
  await expect(doc.locator('[data-unit-id]').first()).toBeVisible()

  await openLessonDetails(page)
  for (const row of report.phases) {
    const li = page.locator(`[data-phase-row="${row.phase}"]`)
    await expect(li).toHaveAttribute('data-status', row.status)
  }
  expect(detail.outline_approved).toBe(true)
  await expect(page.getByTestId('validation-outline')).toContainText('valida')
  await page.getByTestId('details-panel').getByRole('button', { name: /^dettaglio/ }).click()
  await expect(page.getByTestId('cost-panel')).toContainText('Scaletta')

  const markdown = await exportItem(page, 'Markdown')
  await expect(markdown).toHaveAttribute('href', `/api/v1/lessons/${id}/export?format=markdown`)
  const download = page.waitForEvent('download')
  await markdown.click()
  expect((await download).suggestedFilename()).toMatch(/\.md$/)
})

test('dall\'elenco si scaricano i Markdown finali senza aprire la lezione (barra della selezione)', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<(Lesson & { phases: Record<string, string> })[]>(page.request, '/lessons')
  const built = lessons.find((l) => l.phases.build === 'VALID')!
  const notBuilt = lessons.find((l) => l.phases.build !== 'VALID')!
  await page.goto('/')
  const row = (id: number) => page.locator(`[data-testid=lesson-row][data-lesson-id="${id}"]`)
  await page.getByRole('button', { name: 'Seleziona' }).click()
  const bar = page.getByTestId('selection-bar')
  // Senza documento finale il Markdown non c'è: il pulsante resta, non disponibile.
  await row(notBuilt.id).getByRole('checkbox').check()
  await expect(bar.getByRole('button', { name: 'Scarica Markdown' })).toHaveAttribute('aria-disabled', 'true')
  await row(notBuilt.id).getByRole('checkbox').uncheck()

  await row(built.id).getByRole('checkbox').check()
  const download = page.waitForEvent('download')
  await bar.getByRole('link', { name: 'Scarica Markdown' }).click()
  const file = await download
  // Uno ZIP con i documenti finali aggiornati (GET /lesson-exports?format=markdown).
  expect(file.suggestedFilename()).toBe('Lezioni selezionate.zip')
  expect(readFileSync((await file.path())!).subarray(0, 2).toString()).toBe('PK')
  await expect(page).toHaveURL(/\/$/)
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
})

test('avvio di una fase: il job gira sul worker e lo stato resta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FISIOLOGIA')
  await page.goto(`/lezioni/${id}`)
  await openLessonDetails(page)
  const prepare = page.locator('[data-phase-row="prepare"]')
  await expect(prepare).not.toHaveAttribute('data-status', 'VALID')

  await runPhase(page, 'Preparazione')
  await lessonJobs(page)
  await expect(page.getByTestId('jobs-panel')).toContainText('Preparazione')
  await expect(page.getByTestId('jobs-panel').locator('[data-job-state]').first()).toHaveAttribute('data-job-state', 'succeeded', {
    timeout: 45_000,
  })
  await expect(prepare).toHaveAttribute('data-status', 'VALID')

  await page.reload()
  await expect(prepare).toHaveAttribute('data-status', 'VALID')
  const report = await apiGet<PhaseReport>(page.request, `/lessons/${id}/phases`)
  expect(report.phases.find((p) => p.phase === 'prepare')?.status).toBe('VALID')
  await expect(await lessonJobs(page)).toContainText('completato')
})

test('esportazione: Markdown finale e zip completo uguali a quelli dell\'API', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)

  let download = page.waitForEvent('download')
  await (await exportItem(page, 'Markdown')).click()
  const markdown = readFileSync((await (await download).path())!, 'utf-8')
  const fromApi = await page.request.get(`/api/v1/lessons/${id}/export?format=markdown`, { headers: authHeaders() })
  expect(markdown).toBe(await fromApi.text())
  expect(markdown).toContain('# ')

  download = page.waitForEvent('download')
  await (await exportItem(page, /zip/i)).click()
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
  await openLessonDetails(page)
  const build = page.locator('[data-phase-row="build"]')
  await expect(build).toHaveAttribute('data-status', 'MISSING')
  await expect(build.getByTestId('build-warnings')).toContainText('10 issue ancora da valutare')

  // Annulla: nessun job parte
  await runPhase(page, 'Documento')
  const dialog = page.getByRole('dialog', { name: 'Creare il documento finale?' })
  await expect(dialog).toBeVisible()
  for (const w of warnings) await expect(dialog.getByTestId('build-confirm-warnings')).toContainText(w.message)
  await expect(dialog).toContainText('Revisione non aggiornata')
  await dialog.getByRole('button', { name: 'Annulla' }).click()
  await expect(dialog).toBeHidden()
  expect((await apiGet<unknown[]>(page.request, `/jobs?lesson_id=${id}`)).length).toBe(0)

  // Conferma: il documento finale viene creato anche con la revisione non aggiornata
  await runPhase(page, 'Documento')
  await dialog.getByRole('button', { name: 'Crea il documento comunque' }).click()
  await expect((await lessonJobs(page)).locator('[data-job-state]').first()).toHaveAttribute('data-job-state', 'succeeded', {
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

test('intestazione: Domande, Studio, Arricchimento, Verifica, Dettagli ed Esporta sempre nello stesso posto, non disponibili con il motivo', async ({ page }) => {
  await loginViaLink(page)
  const labels = ['Domande', 'Studio', 'Arricchimento', 'Verifica con LLM', 'Dettagli', 'Esporta']
  const actions = page.getByTestId('lesson-actions')

  // Lezione senza rielaborazione: le icone ci sono; Recall, Studio e i download non disponibili, con il motivo
  const setupOnly = await lessonId(page, 'FISIOLOGIA')
  await page.goto(`/lezioni/${setupOnly}`)
  // Nome accessibile = testo del suggerimento, nello stesso ordine del design.
  await expect(actions.locator('a, button')).toHaveCount(6)
  expect(await actions.locator('a, button').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')))).toEqual(labels)
  await expect(actions.getByRole('button', { name: 'Studio' })).toHaveAttribute('aria-disabled', 'true')
  await actions.getByRole('button', { name: 'Studio' }).hover()
  await expect(page.getByRole('tooltip')).toContainText(/rielaborazione/)
  await actions.getByRole('button', { name: 'Esporta' }).click()
  const menu = page.getByRole('menu', { name: 'Esporta' })
  await expect(menu.getByRole('menuitem')).toHaveText([/^Markdown/, /^Tutti i dati \(zip\)/])
  for (const item of await menu.getByRole('menuitem').all()) {
    await expect(item).toHaveAttribute('aria-disabled', 'true')
    await expect(item).toHaveAttribute('title', /rielaborazione/)
  }
  await page.keyboard.press('Escape')
  await expect(menu).toBeHidden()

  // Dettagli e Verifica aprono il pannello laterale; Esc lo chiude
  await actions.getByRole('button', { name: 'Dettagli' }).click()
  await expect(page.getByTestId('lesson-panel')).toHaveAttribute('data-view', 'dettagli')
  await expect(actions.getByRole('button', { name: 'Dettagli' })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByTestId('lesson-details')).toContainText('Stato')
  await actions.getByRole('button', { name: 'Verifica con LLM' }).click()
  await expect(page.getByTestId('lesson-panel')).toHaveAttribute('data-view', 'verifica')
  await expect(page.getByTestId('lesson-review-panel')).toContainText('Mai verificata')
  // Il primo Esc chiude il suggerimento del pulsante col focus, il secondo il pannello.
  await page.keyboard.press('Escape')
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('lesson-panel')).toHaveCount(0)

  // Dopo il rewrite, senza documento finale: tutto disponibile; il Markdown è l'anteprima
  const reviewed = await lessonId(page, 'FARMACOLOGIA')
  const phases = await apiGet<Phases>(page.request, `/lessons/${reviewed}/phases`)
  expect(phases.phases.find((p) => p.phase === 'build')?.status).toBe('MISSING')
  await page.goto(`/lezioni/${reviewed}`)
  await expect(page.getByTestId('lesson-meta')).toContainText(/unità · /)
  await expect(page.getByTestId('document-preview-note')).toHaveText('Bozza')
  const download = page.waitForEvent('download')
  await (await exportItem(page, 'Markdown')).click()
  expect((await download).suggestedFilename()).toMatch(/\(anteprima\)\.md$/)

  // Domande apre il pannello (riempito nel giro 2, G5).
  await actions.getByRole('button', { name: 'Domande' }).click()
  await expect(page.getByTestId('lesson-panel')).toHaveAttribute('data-view', 'domande')
  await page.keyboard.press('Escape')
  await actions.getByRole('link', { name: 'Studio' }).click()
  await expect(page).toHaveURL(new RegExp(`/studio/lezione/${reviewed}$`))
  await page.goto(`/lezioni/${reviewed}`)
  await actions.getByRole('button', { name: 'Arricchimento' }).click()
  await expect(page.getByTestId('lesson-panel')).toHaveAttribute('data-view', 'arricchimento')
  await expect(page.getByTestId('enrichment-panel').getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' })).toBeVisible()
})
