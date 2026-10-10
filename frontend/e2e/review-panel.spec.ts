import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

test('revisione decisa: documento aggiornato automaticamente', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=REVISIONE')
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  await expect(panel).toBeVisible()
  const icon = page.getByTestId('lesson-document').getByRole('button', { name: 'Qualità ASR · statistica', exact: true })
  await expect(icon).toBeVisible()
  await expect(icon.locator('svg')).toBeVisible()
  await expect(page.getByTestId('lesson-document').locator('span[data-review-issue="sci_asr_test"]')).toHaveCount(0)
  await expect(icon.locator('..')).toContainText(/\d{2}:\d{2}/)
  await icon.click()
  await expect(panel.getByTestId('issue-detail')).toContainText('Qualità ASR · statistica')
  await expect(page).toHaveURL(/issue=sci_asr_test/)
  const issues = await apiGet<{ items: { decision: unknown }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
  let remaining = issues.items.filter(i => !i.decision).length
  while (remaining > 0) {
    await panel.getByTestId('issue-detail').getByRole('button', { name: /^Accetta(?: la correzione)?$/ }).click()
    remaining--
    await expect(panel.getByRole('status').first()).toHaveText(remaining ? `${remaining} da decidere su ${issues.items.length}` : 'Tutte decise')
  }
  await expect(panel.getByRole('status').first()).toHaveText('Tutte decise')
  await expect(panel.getByRole('button', { name: 'Riprendi la pipeline' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Ricostruisci il documento', exact: true })).toHaveCount(0)
  await expect.poll(async () => (await apiGet<{ final: boolean }>(page.request, `/lessons/${lesson.id}/document`)).final, { timeout: 30_000 }).toBe(true)
  await expect(panel.getByTestId('documents-status')).toHaveText('Documento aggiornato')
})


test('la correzione proposta si modifica nel box e si applica col clic fuori', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
  const issues = await apiGet<{ items: { issue: { id: string; suggested_fix: string; type: string }; decision: unknown }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
  const item = issues.items.find(i => !i.decision && i.issue.suggested_fix && !['ASR_QUALITY', 'REWRITE_DRIFT'].includes(i.issue.type))!
  await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
  const panel = page.getByTestId('lesson-review-panel')
  await panel.getByTestId('proposed-correction').dblclick()
  const text = item.issue.suggested_fix + ' Correzione verificata.'
  await panel.getByRole('textbox', { name: 'Correzione proposta' }).fill(text)
  await panel.getByRole('status').first().click()
  await expect.poll(async () => (await apiGet<{ items: { issue: { id: string }; decision?: { decision: string; text: string } }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)).items.find(i => i.issue.id === item.issue.id)?.decision?.decision).toBe('edited')
  await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain(text)
  await expect(page.getByTestId('lesson-document')).toContainText('Correzione verificata.')
  await panel.getByRole('button', { name: /^Decise / }).click()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
  await expect(panel.getByTestId('issue-detail')).toContainText('modificata')
})

test('le tacche di Verifica corrispondono all’API e l’icona apre il classificatore', async ({ page }) => {
  const previous = await apiGet<Record<string, unknown>>(page.request, '/settings/classifier')
  const jobs = previous.jobs as Record<string, Record<string, unknown>>
  try {
  const changed = await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: { ...previous, jobs: { ...jobs, relevance: { ...jobs.relevance, mode: 'pipeline' } } } })
  expect(changed.ok()).toBeTruthy()
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=REVISIONE')
  const overview = await apiGet<{ mode: string; units: { review_included: boolean; prediction: string | null; stale: boolean }[] }>(page.request, `/lessons/${lesson.id}/relevance`)
  expect(overview.mode).toBe('active')
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const strip = page.getByTestId('unit-strip-revisore')
  await expect(strip.getByTestId('unit-strip-count')).toHaveText(`${overview.units.filter(u => u.review_included).length}/${overview.units.length}`)
  const ticks = strip.getByTestId('unit-strip-ticks').locator('[data-state]')
  await expect(ticks).toHaveCount(overview.units.length)
  for (let i = 0; i < overview.units.length; i++) {
    const unit = overview.units[i]
    await expect(ticks.nth(i)).toHaveAttribute('data-state', !unit.review_included ? 'excluded' : unit.stale || !unit.prediction ? 'unclassified' : 'included')
  }
  await strip.getByRole('button', { name: /Rivedi le etichette/ }).click()
  await expect(page.locator('[data-testid=lesson-panel][data-view=classificatore]')).toBeVisible()
  } finally {
    await page.goto('about:blank')
    const restored = await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: previous })
    expect(restored.ok()).toBeTruthy()
  }
})

test('tutto verificato: nessuna unità mancante e la ri-verifica globale chiede conferma', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=PATOLOGIA')
  const units = await apiGet<{ state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)
  expect(units.every(unit => ['ok', 'issues'].includes(unit.state))).toBeTruthy()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  let launched = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(`/lessons/${lesson.id}/jobs`)) launched++ })
  await expect(panel.getByRole('button', { name: /^Verifica le unità mancanti/ })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Verifica di nuovo tutta la lezione', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('anche di quelle già verificate')
  await dialog.getByRole('button', { name: 'Annulla' }).click()
  expect(launched).toBe(0)
})

test('Per unità resta acceso dopo il ricaricamento e raggruppa le issue', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
  try {
    await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
    const panel = page.getByTestId('lesson-review-panel')
    const toggle = panel.getByRole('button', { name: 'Per unità', exact: true })
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(async () => (await apiGet<Record<string, unknown>>(page.request, '/preferences'))['review.by-unit']).toBe(true)
    await page.reload()
    await expect(panel.getByRole('button', { name: 'Per unità', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(panel.getByTestId('review-issue-group').first()).toBeVisible()
  } finally {
    await page.request.delete('/api/v1/preferences/review.by-unit', { headers: authHeaders() })
  }
})

test('una correzione dopo una modifica manuale cambia il testo nell’editor', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
  const issues = await apiGet<{ items: { issue: { id: string; claim: string }; decision: unknown; fix_text: string | null }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
  const item = issues.items.find(item => !item.decision && item.fix_text && item.issue.claim.length > 8)!
  expect(item).toBeTruthy()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
  const doc = page.getByTestId('lesson-document')
  await doc.locator('.cm-line').filter({ hasText: item.issue.claim }).first().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' Nota aggiunta a mano prima della decisione.')
  await expect(page.getByTestId('editor-status')).toHaveAttribute('data-status', 'saved')
  await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain('Nota aggiunta a mano prima della decisione.')
  await page.getByTestId('lesson-review-panel').getByTestId('issue-detail').getByRole('button', { name: 'Accetta la correzione', exact: true }).click()
  await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain(item.fix_text!)
  await expect(doc).toContainText(item.fix_text!.replace(/[[\]*_`]/g, ''))
  await expect(doc).toContainText('Nota aggiunta a mano prima della decisione.')
})

test('dalla sezione Unità verifica il testo cambiato e aggiorna la riga', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=PATOLOGIA')
  const units = await apiGet<{ unit_id: string; state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)
  const unit = units.at(-1)!
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  await panel.getByRole('button', { name: /^Unità \d/ }).click()
  let row = panel.locator(`[data-unit="${unit.unit_id}"]`)
  await row.getByRole('button', { name: new RegExp(`^${unit.unit_id}`) }).click()
  const doc = page.getByTestId('lesson-document')
  // Dopo il salto alla riga, l'ultima unità contiene il testo simulato non ancora corretto.
  await doc.locator('.cm-line').filter({ hasText: 'La trattazione scientifica' }).last().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' Unità aggiornata per la nuova verifica.')
  await expect(page.getByTestId('editor-status')).toHaveAttribute('data-status', 'saved')
  row = panel.locator(`[data-unit="${unit.unit_id}"]`)
  await expect(row).toContainText('Testo cambiato')
  // Trattiene la risposta vera per osservare anche l'accodamento del job mock, rapidissimo.
  let release!: () => void
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route(`**/api/v1/lessons/${lesson.id}/jobs`, async route => {
    const response = await route.fetch()
    await responseGate
    await route.fulfill({ response })
  })
  const request = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith(`/lessons/${lesson.id}/jobs`))
  await row.getByRole('button', { name: `Verifica l'unità ${unit.unit_id}`, exact: true }).click()
  expect((await request).postDataJSON()).toMatchObject({ type: 'run_phase', phase: 'review', unit: unit.unit_id })
  try { await expect(row).toContainText('Verifico…') } finally { release() }
  await expect.poll(async () => (await apiGet<{ unit_id: string; state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)).find(item => item.unit_id === unit.unit_id)?.state, { timeout: 120_000 }).toMatch(/^(ok|issues)$/)
  await expect(row).toContainText(/Senza problemi|Con issue/)
  await expect(row.locator('svg').first()).toHaveClass(/text-success|text-warning/)
})
