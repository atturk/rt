import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; pending_issues: number }
type Decision = { issue_id: string; decision: string; channel: string | null; resolved_text: string | null }
type Job = { id: string; state: string }
type IssueItem = {
  issue: { id: string; type: string; severity: string }
  context: { start_s: number | null } | null
  decision: unknown
}

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
  await expect(counter(page)).toHaveText('10 da decidere su 10')
  for (let left = 9; left >= 0; left--) {
    await page.keyboard.press('a')
    await expect(counter(page)).toHaveText(`${left} da decidere su 10`)
  }
  await expect(page.getByTestId('review-notice')).toContainText('la pipeline in attesa è ripartita')
  await expect.poll(async () => (await apiGet<Job>(page.request, `/jobs/${job_id}`)).state, { timeout: 45_000 }).toBe('succeeded')
  await page.reload()
  await expect(counter(page)).toHaveText('0 da decidere su 10')
})

const SEVERITY_RANK = ['high', 'medium', 'low']
const pendingList = (page: Page) => page.getByRole('list', { name: 'Da decidere' }).getByRole('button')

test('review: ordina per gravità, avanza secondo l\'ordine e lo mantiene dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FARMACOLOGIA')
  const { items } = await apiGet<{ items: IssueItem[] }>(page.request, `/lessons/${id}/issues?status=pending`)
  // Atteso dall'API: stesso tipo nelle issue di prova, quindi gravità decrescente, poi timecode, poi ordine dell'API.
  const bySeverity = items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        SEVERITY_RANK.indexOf(a.item.issue.severity) - SEVERITY_RANK.indexOf(b.item.issue.severity) ||
        (a.item.context?.start_s ?? Infinity) - (b.item.context?.start_s ?? Infinity) ||
        a.index - b.index,
    )
    .map((e) => e.item.issue.id)
  expect(new Set(items.map((i) => i.issue.type))).toEqual(new Set(['ERR_CONCETTUALE']))

  await page.goto(`/lezioni/${id}/revisione`)
  await expect(page.getByRole('button', { name: 'Cronologico' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Tipo e gravità' }).click()
  await expect(page).toHaveURL(/ordine=gravita/)
  await expect(pendingList(page)).toHaveCount(bySeverity.length)
  expect(await pendingList(page).evaluateAll((els) => els.map((e) => e.getAttribute('data-issue')))).toEqual(bySeverity)

  // Scegli la prima dell'elenco, decidi: si passa alla seconda secondo la gravità.
  await pendingList(page).first().click()
  await expect(page.getByTestId('issue-detail')).toHaveAttribute('data-issue-id', bySeverity[0])
  await expect(page.getByTestId('issue-detail')).toContainText('gravità alta')
  await page.keyboard.press('a')
  await expect(page.getByTestId('issue-detail')).toHaveAttribute('data-issue-id', bySeverity[1])
  await expect(page.getByTestId('issue-detail')).toContainText('gravità alta')

  await page.reload()
  await expect(page).toHaveURL(/ordine=gravita/)
  await expect(page.getByRole('button', { name: 'Tipo e gravità' })).toHaveAttribute('aria-pressed', 'true')
  expect(await pendingList(page).evaluateAll((els) => els.map((e) => e.getAttribute('data-issue')))).toEqual(bySeverity.slice(1))
  await expect(page.getByTestId('issue-detail')).toHaveAttribute('data-issue-id', bySeverity[1])

  // Il ritorno al cronologico toglie il parametro.
  await page.getByRole('button', { name: 'Cronologico' }).click()
  await expect(page).not.toHaveURL(/ordine=/)
  await page.keyboard.press('u')
  await expect(counter(page)).toHaveText(`${items.length} da decidere su 10`)
})

test('review: niente "Ascolta" né "Job recenti"; il timecode dell\'unità sposta l\'audio', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FARMACOLOGIA')
  await page.goto(`/lezioni/${id}/revisione`)
  const detail = page.getByTestId('issue-detail')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('button', { name: /Ascolta/ })).toHaveCount(0)
  await expect(page.getByText('Job recenti')).toHaveCount(0)

  const issueId = await detail.getAttribute('data-issue-id')
  const { items } = await apiGet<{ items: (IssueItem & { issue: { unit_id: string } })[] }>(page.request, `/lessons/${id}/issues?status=all`)
  const item = items.find((i) => i.issue.id === issueId)!
  const timecode = page.getByTestId('lesson-document').locator(`[data-unit-id="${item.issue.unit_id}"] .rt-timecode`)
  await expect(timecode).toBeEnabled()
  const seconds = Number(await timecode.getAttribute('data-seconds'))
  await page.locator('audio').evaluate((a: HTMLAudioElement) => (a.muted = true))
  await timecode.click()
  await expect
    .poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.currentTime))
    .toBeGreaterThanOrEqual(seconds)
  await expect(page.getByTestId('lesson-document')).toHaveAttribute('data-active-unit', item.issue.unit_id)
})

test('player: velocità con lo slider da tastiera, uguale in lezione e revisione dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'FARMACOLOGIA')
  await page.goto(`/lezioni/${id}/revisione`)
  const speed = page.getByRole('button', { name: /^Velocità di riproduzione/ })
  await expect(speed).toHaveText('1×')
  const before = await counter(page).textContent()
  const selected = await page.getByTestId('issue-detail').getAttribute('data-issue-id')
  await speed.focus()
  await page.keyboard.press('Enter')
  const slider = page.getByRole('slider', { name: 'Velocità di riproduzione' })
  await expect(slider).toBeFocused()
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('speed-value')).toHaveText('1.25×')
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByTestId('speed-value')).toHaveText('1.2×')
  await expect.poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.playbackRate)).toBeCloseTo(1.2)
  // Le frecce nello slider non muovono le issue né decidono.
  await expect(counter(page)).toHaveText(before!)
  await expect(page.getByTestId('issue-detail')).toHaveAttribute('data-issue-id', selected!)
  await page.keyboard.press('Escape')
  await expect(slider).toHaveCount(0)
  await expect(speed).toBeFocused()
  await expect(speed).toHaveText('1.2×')

  // Clic fuori chiude lo slider.
  await speed.click()
  await expect(slider).toBeVisible()
  await page.getByRole('heading', { level: 1 }).click()
  await expect(slider).toHaveCount(0)

  await page.reload()
  await expect(speed).toHaveText('1.2×')
  await page.goto(`/lezioni/${id}`)
  await expect(page.getByRole('button', { name: /^Velocità di riproduzione/ })).toHaveText('1.2×')
  await expect.poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.playbackRate)).toBeCloseTo(1.2)
})
