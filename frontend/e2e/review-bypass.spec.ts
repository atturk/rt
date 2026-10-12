import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

test('il menu di una unità esclusa esegue il revisore senza modificare l’esclusione', async ({ page }) => {
  const previous = await apiGet<Record<string, unknown>>(page.request, '/settings/classifier')
  const jobs = previous.jobs as Record<string, Record<string, unknown>>
  let unitPath: string | undefined
  let priorOverride: string | null = null
  try {
    expect((await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: { ...previous, jobs: { ...jobs, relevance: { ...jobs.relevance, mode: 'pipeline' } } } })).ok()).toBeTruthy()
    await loginViaLink(page)
    const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=PATOLOGIA')
    const before = await apiGet<{ units: { unit_id: string; override: string | null }[] }>(page.request, `/lessons/${lesson.id}/relevance`)
    const unit = before.units[0]
    unitPath = `/api/v1/lessons/${lesson.id}/relevance/${unit.unit_id}`
    priorOverride = unit.override
    expect((await page.request.put(unitPath, { headers: authHeaders(), data: { category: 'organizational' } })).ok()).toBeTruthy()
    await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
    const panel = page.getByTestId('lesson-review-panel')
    await panel.getByRole('button', { name: 'Mostra decise' }).click()
    const row = panel.locator(`[data-unit="${unit.unit_id}"]`)
    await expect(row).toHaveAttribute('data-testid', 'review-unit-excluded')
    await expect(row.getByRole('button', { name: 'Apri il Classificatore' })).toBeVisible()
    await row.getByRole('button', { name: `Azioni sull’unità ${unit.unit_id}` }).click()
    await expect(page.getByRole('menuitem', { name: /Riesegui/ })).toHaveCount(0)
    const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/lessons/${lesson.id}/jobs`))
    await page.getByRole('menuitem', { name: 'Esegui senza classificatore' }).click()
    const launched = await response
    expect(launched.request().postDataJSON()).toMatchObject({ phase: 'review', unit: unit.unit_id, force: true, skip_prefilter: true, include_excluded: true })
    const { job_id: id } = await launched.json()
    await expect.poll(async () => (await apiGet<{ state: string }>(page.request, `/jobs/${id}`)).state).toBe('succeeded')
    const result = await apiGet<{ result: { units: { unit: string; issues: number }[] } }>(page.request, `/jobs/${id}`)
    expect(result.result.units).toEqual([expect.objectContaining({ unit: unit.unit_id, issues: expect.any(Number) })])
    const after = await apiGet<{ units: { unit_id: string; override: string | null; review_included: boolean }[] }>(page.request, `/lessons/${lesson.id}/relevance`)
    expect(after.units.find(u => u.unit_id === unit.unit_id)).toMatchObject({ override: 'organizational', review_included: false })
    await expect(row).toHaveAttribute('data-testid', 'review-unit-excluded')
  } finally {
    await page.goto('about:blank')
    if (unitPath) expect((await page.request.put(unitPath, { headers: authHeaders(), data: { category: priorOverride } })).ok()).toBeTruthy()
    expect((await page.request.put('/api/v1/settings/classifier', { headers: authHeaders(), data: previous })).ok()).toBeTruthy()
  }
})
