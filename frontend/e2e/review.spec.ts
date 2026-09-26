import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; pending_issues: number }
type Decision = { issue_id: string; decision: string; channel: string | null; resolved_text: string | null }
type Job = { id: string; state: string }

async function lessonId(page: Page, materia: string) {
  const [lesson] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return lesson.id
}

const counter = (page: Page) => page.getByTestId('review-counter')

test('review: accetta, mantieni, modifica, annulla; il ledger resta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FARMACOLOGIA')
  await page.locator(`[data-testid=lesson-card][data-lesson-id="${id}"]`).getByRole('link', { name: /issue da valutare/ }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${id}/revisione`))
  await expect(counter(page)).toHaveText('10 da decidere su 10')
  await expect(page.getByTestId('issue-diff')).toBeVisible()
  await expect(page.locator('mark.rt-claim')).toBeVisible()

  const first = await page.getByTestId('issue-detail').getAttribute('data-issue-id')
  await page.keyboard.press('a')
  await expect(counter(page)).toHaveText('9 da decidere su 10')
  await expect(page.getByTestId('issue-detail')).not.toHaveAttribute('data-issue-id', first!)

  const second = await page.getByTestId('issue-detail').getAttribute('data-issue-id')
  await page.getByRole('button', { name: /Mantieni originale/ }).click()
  await expect(counter(page)).toHaveText('8 da decidere su 10')

  const third = await page.getByTestId('issue-detail').getAttribute('data-issue-id')
  await page.keyboard.press('e')
  await page.getByLabel('Testo corretto').fill('Testo corretto a mano dalla SPA.')
  await page.getByRole('button', { name: 'Salva modifica' }).click()
  await expect(counter(page)).toHaveText('7 da decidere su 10')

  await page.keyboard.press('u')
  await expect(counter(page)).toHaveText('8 da decidere su 10')
  await expect(page.getByTestId('issue-detail')).toHaveAttribute('data-issue-id', third!)

  await page.reload()
  await expect(counter(page)).toHaveText('8 da decidere su 10')
  await expect(page.getByRole('list', { name: 'Decise' }).getByRole('button')).toHaveCount(2)

  const ledger = await apiGet<Decision[]>(page.request, `/lessons/${id}/decisions`)
  expect(ledger.map((d) => [d.issue_id, d.decision, d.channel])).toEqual([
    [first, 'accepted', 'api'],
    [second, 'rejected', 'api'],
  ])
  const lesson = await apiGet<Lesson>(page.request, `/lessons/${id}`)
  expect(lesson.pending_issues).toBe(8)
})

test('review: con l\'ultima decisione la pipeline in attesa riparte', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'PATOLOGIA')
  // Pipeline in mock che si ferma sulle issue da decidere (come 'rt run' senza --auto-accept).
  const res = await page.request.post(`/api/v1/lessons/${id}/jobs`, {
    headers: authHeaders(),
    data: { type: 'run_pipeline', mock: true, auto_accept: false, rename: false },
  })
  expect(res.status()).toBe(202)
  const { job_id } = (await res.json()) as { job_id: string }
  await expect.poll(async () => (await apiGet<Job>(page.request, `/jobs/${job_id}`)).state, { timeout: 45_000 }).toBe('waiting_for_decision')

  await page.goto(`/lezioni/${id}/revisione`)
  await expect(page.getByTestId('jobs-panel')).toContainText('serve una tua decisione')
  for (let left = 9; left >= 0; left--) {
    await page.keyboard.press('a')
    await expect(counter(page)).toHaveText(`${left} da decidere su 10`)
  }
  await expect(page.getByTestId('review-notice')).toContainText('la pipeline in attesa è ripartita')
  await expect.poll(async () => (await apiGet<Job>(page.request, `/jobs/${job_id}`)).state, { timeout: 45_000 }).toBe('succeeded')
  await page.reload()
  await expect(counter(page)).toHaveText('0 da decidere su 10')
  await expect(page.getByTestId('jobs-panel')).toContainText('completato')
})
