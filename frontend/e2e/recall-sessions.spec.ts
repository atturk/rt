import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// Sessioni di ripasso (G4): il tipo resta l'ultimo usato, "Termina" chiude la sessione sul backend
// con il riepilogo. Il recall su Telegram dall'app non c'è più (Telegram spento di predefinito):
// restano le API, provate dai test del backend.

type Lesson = { id: number; materia: string; phases: Record<string, string> }
type Summary = { questions: number; answered: number }
type SessionInfo = { id: number; state: string; summary?: Summary | null }
type SessionState = { web: SessionInfo | null; last: SessionInfo | null }
type Overview = { questions: Record<string, Record<string, number>> }

async function openSession(page: Page) {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const lesson = lessons.find((l) => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')!
  const overview = await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)
  if (!(overview.questions.quiz?.pending ?? 0)) {
    const res = await page.request.post(`/api/v1/lessons/${lesson.id}/recall/generate`, { headers: authHeaders(), data: { qtype: 'quiz', mock: true } })
    expect(res.ok(), await res.text()).toBeTruthy()
    await expect.poll(async () => (await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)).questions.quiz?.pending ?? 0, { timeout: 30_000 }).toBeGreaterThan(0)
  }
  await page.goto(`/lezioni/${lesson.id}/sessione`)
  return lesson
}

async function sessionState(page: Page, lessonId: number) {
  return apiGet<SessionState>(page.request, `/lessons/${lessonId}/recall/session`)
}

test('tipo di domanda: resta l\'ultimo usato dopo la ricarica', async ({ page }) => {
  await openSession(page)
  const types = page.getByRole('group', { name: 'Tipo di domanda' })
  await types.getByRole('button', { name: 'Vasta', exact: true }).click()
  await expect(types.getByRole('button', { name: 'Vasta', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Vasta', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Quiz', exact: true }).click()
})

test('termina: la sessione si chiude sul backend con il riepilogo e si torna alla lezione', async ({ page }) => {
  const lesson = await openSession(page)
  await page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Quiz', exact: true }).click()
  await page.getByRole('button', { name: /^A\./ }).click()
  await page.getByRole('button', { name: 'Rispondi' }).click()
  await expect(page.getByTestId('recall-result-card')).toBeVisible()
  await expect.poll(async () => (await sessionState(page, lesson.id)).web?.state).toBe('active')

  await page.getByRole('button', { name: 'Termina' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}$`))
  const state = await sessionState(page, lesson.id)
  expect(state.web).toBeNull()
  expect(state.last?.state).toBe('ended')
  expect(state.last?.summary?.answered).toBeGreaterThanOrEqual(1)
})
