import { writeFile } from 'node:fs/promises'
import path from 'node:path'
import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, serverState } from './support'

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
    await panel.getByTestId('issue-detail').getByRole('button', { name: /^(?:Accetta(?: la correzione| il testo)?|Ho controllato)$/ }).click()
    remaining--
    await expect(panel.getByRole('status').first()).toContainText(remaining ? `${remaining} da decidere` : 'Tutte decise')
  }
  await expect(panel.getByRole('status').first()).toContainText('Tutte decise')
  await expect(panel.getByRole('button', { name: 'Riprendi la pipeline' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Ricostruisci il documento', exact: true })).toHaveCount(0)
  await expect.poll(async () => (await apiGet<{ final: boolean }>(page.request, `/lessons/${lesson.id}/document`)).final, { timeout: 30_000 }).toBe(true)
  await expect(panel.getByTestId('documents-status')).toContainText('Documento aggiornato')
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
  await panel.getByRole('button', { name: 'Mostra decise' }).click()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
  await panel.getByRole('button', { name: 'Mostra decise' }).click()
  await expect(panel.getByTestId('issue-detail')).toContainText('modificata')
  await expect(panel.getByTestId('issue-detail').getByRole('button')).toHaveCount(1)
})

test('le unità di Verifica corrispondono all’API e le escluse aprono il classificatore', async ({ page }) => {
  const previous = await apiGet<Record<string, unknown>>(page.request, '/settings/classifier')
  const jobs = previous.jobs as Record<string, Record<string, unknown>>
  let unitPath: string | undefined
  let priorOverride: string | null = null
  try {
    const changed = await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: { ...previous, jobs: { ...jobs, relevance: { ...jobs.relevance, mode: 'pipeline' } } } })
    expect(changed.ok()).toBeTruthy()
    await loginViaLink(page)
    const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=REVISIONE')
    const before = await apiGet<{ units: { unit_id: string; override: string | null }[] }>(page.request, `/lessons/${lesson.id}/relevance`)
    unitPath = `/api/v1/lessons/${lesson.id}/relevance/${before.units[0].unit_id}`
    priorOverride = before.units[0].override
    const excluded = await page.request.put(unitPath, { headers: authHeaders(), data: { category: 'organizational' } })
    expect(excluded.ok()).toBeTruthy()
    const overview = await apiGet<{ mode: string; units: { unit_id: string; review_included: boolean }[] }>(page.request, `/lessons/${lesson.id}/relevance`)
    expect(overview.mode).toBe('active')
    await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
    const panel = page.getByTestId('lesson-review-panel')
    await panel.getByRole('button', { name: 'Mostra decise' }).click()
    await expect(panel.getByTestId('unit-strip-revisore')).toHaveCount(0)
    const rows = panel.getByRole('list', { name: 'Unità della verifica' }).locator(':scope > li')
    await expect(rows).toHaveCount(overview.units.length)
    for (const unit of overview.units) {
      const row = panel.locator(`[data-unit="${unit.unit_id}"]`)
      await expect(row).toHaveAttribute('data-testid', unit.review_included ? /review-unit-(ok|issues|never|changed|failed)/ : 'review-unit-excluded')
    }
    await panel.getByTestId('review-unit-excluded').first().getByRole('button', { name: 'Apri il Classificatore' }).click()
    await expect(page).toHaveURL(/panel=classificatore/)
    await expect(page.locator('[data-testid=lesson-panel][data-view=classificatore]')).toBeVisible()
  } finally {
    await page.goto('about:blank')
    if (unitPath) expect((await page.request.put(unitPath, { headers: authHeaders(), data: { category: priorOverride } })).ok()).toBeTruthy()
    expect((await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: previous })).ok()).toBeTruthy()
  }
})

test('tutto verificato: nessuna unità mancante e la ri-verifica globale parte subito', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=PATOLOGIA')
  const units = await apiGet<{ state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)
  expect(units.every(unit => ['ok', 'issues'].includes(unit.state))).toBeTruthy()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  const launched = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith(`/lessons/${lesson.id}/jobs`))
  await expect(panel.getByRole('button', { name: /^Verifica le unità mancanti/ })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Azioni della verifica' }).click()
  await page.getByRole('menuitem', { name: 'Riesegui tutta la lezione' }).click()
  expect((await launched).postDataJSON()).toMatchObject({ type: 'run_phase', phase: 'review', force: true })
  await expect(panel.getByRole('group', { name: /Riesegui/ })).toHaveCount(0)
  await expect.poll(async () => (await apiGet<{ state: string }[]>(page.request, `/jobs?lesson_id=${lesson.id}&limit=1`))[0].state).toBe('succeeded')
})

test('l’elenco resta per unità dopo il ricaricamento e conserva l’ordine', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  await expect(panel.getByRole('button', { name: 'Per unità', exact: true })).toHaveCount(0)
  await expect(panel.getByTestId('review-issue-group').first()).toBeVisible()
  const previous = (await apiGet<Record<string, unknown>>(page.request, '/preferences'))['review.order'] ?? 'cronologico'
  await panel.getByRole('button', { name: 'Ordine delle issue' }).click()
  const order = previous === 'gravita' ? 'cronologico' : 'gravita'
  await expect.poll(async () => (await apiGet<Record<string, unknown>>(page.request, '/preferences'))['review.order']).toBe(order)
  await page.reload()
  await expect(panel.getByTestId('review-issue-group').first()).toBeVisible()
  await panel.getByRole('button', { name: 'Ordine delle issue' }).hover()
  await expect(page.getByRole('tooltip')).toContainText(order === 'gravita' ? 'Gravità' : 'Cronologico')
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

test('dall’elenco unico verifica il testo cambiato e aggiorna la riga', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=PATOLOGIA')
  const units = await apiGet<{ unit_id: string; state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)
  const unit = units.at(-1)!
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
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
  try { await expect(row).toContainText(/In coda|In corso/) } finally { release() }
  await expect.poll(async () => (await apiGet<{ unit_id: string; state: string }[]>(page.request, `/lessons/${lesson.id}/review/units`)).find(item => item.unit_id === unit.unit_id)?.state, { timeout: 120_000 }).toMatch(/^(ok|issues)$/)
  await expect(row).toContainText(/Senza problemi|Con issue/)
  await expect(row.locator('svg[aria-label="Senza problemi"], svg[aria-label="Con issue"]')).toHaveClass(/text-success|text-warning/)
})


test('la verifica mostra le issue finite e permette di decidere mentre un’altra unità lavora', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number; path: string }[]>(page.request, '/lessons?materia=VERIFICA%20LIVE')
  const relative = path.relative(serverState().lessons_root, lesson.path)
  expect(relative).not.toMatch(/^\.\.|^[/\\]/)
  const release = path.join(serverState().lessons_root, '.review-live.release')
  try {
    await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
    const panel = page.getByTestId('lesson-review-panel')
    await panel.getByRole('button', { name: 'Verifica', exact: true }).click()
    const first = panel.locator('[data-unit="1.1"]')
    const second = panel.locator('[data-unit="1.2"]')
    await expect(first.getByTestId('issue-detail')).toBeVisible({ timeout: 30_000 })
    await expect(second).toContainText('In corso')
    const current = await apiGet<{ items: { issue: { id: string; unit_id: string }; fix_text: string | null; decision: unknown }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
    const item = current.items.find(item => item.issue.unit_id === '1.1' && !item.decision && item.fix_text)!
    expect(item).toBeTruthy()
    await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
    const accept = panel.getByTestId('issue-detail').getByRole('button', { name: 'Accetta la correzione', exact: true })
    await expect(accept).toBeEnabled()
    await accept.click()
    await expect.poll(async () => (await apiGet<{ items: { issue: { id: string }; decision: unknown }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)).items.find(row => row.issue.id === item.issue.id)?.decision).toBeTruthy()
    await expect(second).toContainText('In corso')
    await expect(panel.getByTestId('review-decision-message').getByRole('button', { name: 'Annulla' })).toBeEnabled()
    await expect(page.getByTestId('lesson-document')).toContainText(item.fix_text!.replace(/[[\]*_`]/g, ''))
    await expect(panel.getByRole('button', { name: 'Ricostruisci il documento', exact: true })).toHaveCount(0)
  } finally {
    await writeFile(release, 'prosegui')
  }
  await expect.poll(async () => (await apiGet<{ type: string; state: string }[]>(page.request, `/jobs?lesson_id=${lesson.id}`)).some(job => job.type !== 'documents' && ['queued', 'running'].includes(job.state)), { timeout: 30_000 }).toBe(false)
})
