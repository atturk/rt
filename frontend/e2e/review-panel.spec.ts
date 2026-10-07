import { expect } from '@playwright/test'
import { test, apiGet, loginViaLink } from './support'

test('revisione decisa: ricostruisce con run_phase build', async ({ page }) => {
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
  const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/lessons/${lesson.id}/jobs`))
  await panel.getByRole('button', { name: 'Ricostruisci il documento', exact: true }).click()
  if (await page.getByRole('button', { name: 'Crea il documento comunque' }).count()) await page.getByRole('button', { name: 'Crea il documento comunque' }).click()
  expect((await request).postDataJSON()).toMatchObject({ type: 'run_phase', phase: 'build' })
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
