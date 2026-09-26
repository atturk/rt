import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// RT4-F7: il percorso completo di una lezione nuova solo dalla SPA, come 'rt run' da terminale:
// accesso con il link, importazione dell'audio, scaletta, review di tutte le issue, build,
// lettura del documento con l'audio, recall. Dopo ogni passo la pagina si ricarica e quello che
// mostra deve venire dal backend.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; state: string; lesson_id: number | null; decision: { kind: string } | null }
type Lesson = { id: number; materia: string; pending_issues: number; phases: Record<string, string> }
type Outline = { approved: boolean }
type IssueList = { total: number }
type Decision = { issue_id: string; decision: string }
type History = { questions: { id: string; status: string }[]; answers: { question_id: string }[] }

async function job(page: Page, id: string) {
  return apiGet<Job>(page.request, `/jobs/${id}`)
}

async function waitJob(page: Page, id: string, check: (j: Job) => boolean) {
  await expect.poll(async () => check(await job(page, id)), { timeout: LONG, intervals: [500] }).toBe(true)
}

test('percorso completo: dall\'audio al recall, con ricarica dopo ogni passo', async ({ page }) => {
  test.setTimeout(8 * LONG)

  // 1. Accesso con il link monouso: la sessione resta dopo la ricarica.
  await loginViaLink(page)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeAttached()

  // 2. Importazione dell'audio con la pipeline (in prova), che si ferma sulla scaletta.
  await page.goto('/importa')
  await page.getByLabel('File audio', { exact: true }).setInputFiles(AUDIO)
  await page.getByLabel('Data', { exact: true }).fill('2026-09-25')
  await page.getByLabel('Materia', { exact: true }).fill('EMBRIOLOGIA')
  await page.getByLabel('Argomenti', { exact: true }).fill('Gastrulazione')
  await page.getByLabel('Avvia subito la pipeline').setChecked(true)
  await page.getByText('Opzioni avanzate').click()
  await page.getByLabel('Modalità prova (mock)').check()
  await page.getByRole('button', { name: 'Importa' }).click()
  await expect(page).toHaveURL(/\/job\/[0-9a-f-]+$/)
  const jobId = page.url().split('/job/')[1]
  await waitJob(page, jobId, (j) => j.decision?.kind === 'outline_approval')
  await page.reload()
  await expect(page.getByTestId('job-live').first()).toHaveAttribute('data-state', 'waiting_for_decision')
  const lessonId = (await job(page, jobId)).lesson_id!
  expect((await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)).materia).toBe('EMBRIOLOGIA')

  // 3. Approvazione della scaletta dalla lezione.
  await page.goto(`/lezioni/${lessonId}`)
  await page.getByTestId('lesson-waiting').getByRole('link', { name: 'Rivedi la scaletta' }).click()
  await page.getByRole('button', { name: 'Approva la scaletta' }).click()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'true')
  await page.reload()
  await expect(page.getByTestId('outline-approved')).toHaveAttribute('data-approved', 'true')
  expect((await apiGet<Outline>(page.request, `/lessons/${lessonId}/outline`)).approved).toBe(true)

  // 4. Review di tutte le issue: la pipeline riparte da sola e arriva al build.
  await waitJob(page, jobId, (j) => j.decision?.kind === 'science_issue')
  const { total } = await apiGet<IssueList>(page.request, `/lessons/${lessonId}/issues?status=all`)
  expect(total).toBeGreaterThan(0)
  await page.goto(`/lezioni/${lessonId}`)
  await page.getByRole('link', { name: /issue da valutare|Rivedi/ }).first().click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lessonId}/revisione`))
  const counter = page.getByTestId('review-counter')
  await expect(counter).toHaveText(`${total} da decidere su ${total}`)
  for (let left = total - 1; left >= 0; left--) {
    await page.keyboard.press('a')
    await expect(counter).toHaveText(`${left} da decidere su ${total}`)
  }
  await page.reload()
  await expect(counter).toHaveText(`0 da decidere su ${total}`)
  const decisions = await apiGet<Decision[]>(page.request, `/lessons/${lessonId}/decisions`)
  expect(decisions.map((d) => d.decision)).toEqual(Array(total).fill('accepted'))
  await waitJob(page, jobId, (j) => j.state === 'succeeded')

  // 5. Documento finale con l'audio: build valido, unità con timecode, player.
  await page.goto(`/lezioni/${lessonId}`)
  await page.reload()
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'VALID')
  expect((await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)).phases.build).toBe('VALID')
  await expect(page.getByTestId('lesson-document').locator('[data-unit-id]').first()).toBeVisible()
  await expect(page.locator('audio')).toHaveCount(1)

  // 6. Recall sulla lezione nuova: riserva, una domanda quiz, risposta riletta dopo la ricarica.
  await page.goto(`/lezioni/${lessonId}/recall`)
  await page.getByRole('button', { name: 'Genera la riserva iniziale' }).click()
  await expect(page.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded', { timeout: LONG })
  await page.getByRole('radio', { name: 'Quiz' }).click()
  await page.getByRole('button', { name: 'Prossima domanda' }).click()
  const question = page.getByTestId('recall-question')
  await expect(question).toBeVisible()
  const questionId = (await question.getAttribute('data-question-id'))!
  await question.getByRole('radio').first().check()
  await page.getByRole('button', { name: 'Rispondi' }).click()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  await page.reload()
  await expect(page.locator(`[data-testid=history-item][data-question-id="${questionId}"]`)).toBeVisible()
  const history = await apiGet<History>(page.request, `/lessons/${lessonId}/recall/history`)
  expect(history.questions.find((q) => q.id === questionId)?.status).toBe('answered')
  expect(history.answers.some((a) => a.question_id === questionId)).toBe(true)
})
