import { expect } from '@playwright/test'
import { test, apiGet, loginViaLink } from './support'

test('revisione decisa: ricostruisce con run_phase build', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=REVISIONE')
  await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
  const panel = page.getByTestId('lesson-review-panel')
  await expect(panel).toBeVisible()
  const issues = await apiGet<{ items: { decision: unknown }[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
  let remaining = issues.items.filter(i => !i.decision).length
  while (remaining > 0) {
    await panel.getByTestId('issue-detail').getByRole('button', { name: 'Accetta', exact: true }).click()
    remaining--
    await expect(panel.getByRole('status').first()).toHaveText(remaining ? `${remaining} da decidere su ${issues.items.length}` : 'Tutte decise')
  }
  await expect(panel.getByRole('status').first()).toHaveText('Tutte decise')
  await expect(panel.getByRole('button', { name: 'Riprendi la pipeline' })).toHaveCount(0)
  const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/lessons/${lesson.id}/jobs`))
  await panel.getByRole('button', { name: 'Ricostruisci il documento', exact: true }).click()
  if (await page.getByRole('button', { name: 'Crea il documento comunque' }).count()) await page.getByRole('button', { name: 'Crea il documento comunque' }).click()
  expect((await request).postDataJSON()).toMatchObject({ type: 'run_phase', phase: 'build' })
})
