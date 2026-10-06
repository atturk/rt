import { expect, type Page } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink } from './support'

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
  // Il clic sull'alternativa è già la risposta (4.2.2b3): non c'è più "Rispondi" nel quiz.
  await page.getByRole('button', { name: /^A\./ }).click()
  await expect(page.getByTestId('recall-result-card')).toBeVisible()
  await expect.poll(async () => (await sessionState(page, lesson.id)).web?.state).toBe('active')

  await page.getByRole('button', { name: 'Termina' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}$`))
  const state = await sessionState(page, lesson.id)
  expect(state.web).toBeNull()
  expect(state.last?.state).toBe('ended')
  expect(state.last?.summary?.answered).toBeGreaterThanOrEqual(1)
})

type Bank = { questions: { id: string; status: string; question_text: string; type: string }[] }

const bank = (page: Page, lessonId: number) => apiGet<Bank>(page.request, `/lessons/${lessonId}/recall/history`)

test('pannello Domande: elenco contraibile, filtro per stato, modifica a mano e riproposta delle poste', async ({ page }) => {
  const lesson = await openSession(page)
  await page.goto(`/lezioni/${lesson.id}?panel=domande`)
  const panel = page.getByTestId('questions-panel')
  const toggle = panel.getByTestId('questions-list-toggle')
  await expect(toggle).toContainText('Domande della lezione')

  // Si contrae e si riapre.
  await toggle.click()
  await expect(panel.getByTestId('questions-list-body')).toBeHidden()
  await toggle.click()
  await expect(panel.getByTestId('questions-list')).toBeVisible()

  // Filtro per stato: solo quelle da porre.
  await panel.getByRole('group', { name: 'Filtra per stato' }).getByRole('button', { name: 'Da porre' }).click()
  const row = panel.getByTestId('questions-list').locator('li').first()
  await expect(row).toContainText('da porre')

  // Modifica a mano dal menu "...": il testo cambia e la domanda resta fra quelle da porre.
  const before = (await row.textContent())!
  await row.getByRole('button', { name: 'Azioni sulla domanda' }).click()
  await page.getByRole('menuitem', { name: 'Modifica' }).click()
  const modal = page.getByTestId('question-edit-modal')
  await expect(modal).toBeVisible()
  const text = `Domanda corretta a mano ${Date.now()}?`
  await modal.getByLabel('Testo della domanda').fill(text)
  await modal.getByTestId('question-edit-save').click()
  await expect(modal).toBeHidden()
  await expect(panel.getByTestId('questions-list')).toContainText(text)
  expect(before).not.toContain(text)
  await expect.poll(async () => (await bank(page, lesson.id)).questions.find((q) => q.question_text === text)?.status).toBe('pending')

  // Segnata come posta, il pulsante la ripesca.
  const edited = (await bank(page, lesson.id)).questions.find((q) => q.question_text === text)!
  const editedRow = panel.getByTestId('questions-list').locator('li', { hasText: text })
  await panel.getByRole('group', { name: 'Filtra per stato' }).getByRole('button', { name: 'Tutte' }).click()
  await editedRow.getByRole('button', { name: 'Azioni sulla domanda' }).click()
  await page.getByRole('menuitem', { name: 'Segna come posta' }).click()
  await expect.poll(async () => (await bank(page, lesson.id)).questions.find((q) => q.id === edited.id)?.status).toBe('asked')

  const restore = panel.getByTestId('questions-restore')
  await expect(restore).toBeVisible()
  await expect(restore.getByRole('button', { name: /Riproponi le poste/ })).toBeVisible()
  await restore.getByRole('button', { name: /Riproponi le poste/ }).click()
  await expect.poll(async () => (await bank(page, lesson.id)).questions.find((q) => q.id === edited.id)?.status).toBe('pending')
})
