import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// RT4-FA7: sessioni di recall. "Termina sessione" con riepilogo salvato, selettori a slitta
// (luogo e tipo di domanda) da tastiera, avvio e interruzione su Telegram tramite il bot finto
// (RT_TELEGRAM_FAKE=1: esegue le richieste dell'app sulla Bot API finta, domande in mock).

type Lesson = { id: number; phases: Record<string, string> }
type Summary = { questions: number; answered: number; quiz_answered: number; correct: number }
type SessionInfo = { id: number; lesson_id: number | null; state: string; channel: string; summary?: Summary | null }
type SessionState = { web: SessionInfo | null; last: SessionInfo | null; telegram: SessionInfo | null }
type Overview = { questions: Record<string, Record<string, number>> }

async function openRecall(page: Page) {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const lesson = lessons.find((l) => l.phases.build === 'VALID')!
  await page.goto(`/lezioni/${lesson.id}/recall`)
  const overview = await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)
  if (Object.keys(overview.questions).length === 0) {
    await page.getByRole('button', { name: 'Genera la riserva iniziale' }).click()
    await expect(page.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded', { timeout: 30_000 })
  }
  return lesson
}

async function sessionState(page: Page, lessonId: number) {
  return apiGet<SessionState>(page.request, `/lessons/${lessonId}/recall/session`)
}

/** Chiude dal backend una sessione web lasciata aperta da un altro test. */
async function endWebSession(page: Page, lessonId: number) {
  if ((await sessionState(page, lessonId)).web) {
    const res = await page.request.post(`/api/v1/lessons/${lessonId}/recall/session/end`, { headers: authHeaders() })
    expect(res.ok()).toBeTruthy()
  }
}

test('tipo di domanda: slitta a tre stati da tastiera, scelta riletta dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  const group = page.getByRole('radiogroup', { name: 'Tipo di domanda' })
  const toggle = page.getByTestId('type-toggle')
  await expect(group.getByRole('radio', { name: 'Quiz' })).toHaveAttribute('aria-checked', 'true')
  await expect(toggle).toContainText('Quiz: Scelta multipla, esito immediato')

  // un solo tab stop: l'opzione scelta
  await expect(group.getByRole('radio', { name: 'Mirata' })).toHaveAttribute('tabindex', '-1')
  await group.getByRole('radio', { name: 'Quiz' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(group.getByRole('radio', { name: 'Mirata' })).toHaveAttribute('aria-checked', 'true')
  await expect(group.getByRole('radio', { name: 'Mirata' })).toBeFocused()
  await expect(toggle).toContainText('Mirata: Domanda aperta su un punto preciso')
  await page.keyboard.press('ArrowRight')
  await expect(group.getByRole('radio', { name: 'Vasta' })).toHaveAttribute('aria-checked', 'true')
  await expect(toggle).toContainText('Vasta: Domanda aperta di collegamento')
  await page.keyboard.press('ArrowRight')
  await expect(group.getByRole('radio', { name: 'Quiz' })).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('ArrowLeft')
  await expect(group.getByRole('radio', { name: 'Vasta' })).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('Home')
  await expect(group.getByRole('radio', { name: 'Quiz' })).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('End')
  await expect(toggle).toHaveAttribute('data-value', 'vasta')

  await page.reload()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/recall\\?.*tipo=vasta`))
  await expect(page.getByRole('radiogroup', { name: 'Tipo di domanda' }).getByRole('radio', { name: 'Vasta' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
})

test('termina sessione: riepilogo salvato dal backend e riletto dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  await endWebSession(page, lesson.id)
  await page.reload()
  await expect(page.getByRole('radiogroup', { name: 'Dove fare il recall' }).getByRole('radio', { name: 'Qui', exact: true })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  await expect(page.getByTestId('place-toggle')).toContainText('Recall qui')
  await expect(page.getByRole('button', { name: 'Termina sessione' })).toHaveCount(0)

  await page.getByRole('radio', { name: 'Quiz' }).click()
  await page.getByRole('button', { name: 'Prossima domanda' }).click()
  await expect(page.getByTestId('recall-question')).toBeVisible()
  await page.getByTestId('recall-question').getByRole('radio').first().check()
  await page.getByRole('button', { name: 'Rispondi' }).click()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  await page.getByRole('button', { name: 'Prossima domanda' }).click()
  await expect(page.getByTestId('web-session')).toContainText('domande poste: 2')

  await page.getByRole('button', { name: 'Termina sessione' }).click()
  const summary = page.getByTestId('session-summary')
  await expect(summary).toBeVisible()
  await expect(page.getByTestId('recall-question')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Termina sessione' })).toHaveCount(0)

  await page.reload()
  await expect(summary).toBeVisible()
  const state = await sessionState(page, lesson.id)
  expect(state.web).toBeNull()
  expect(state.last?.state).toBe('ended')
  const saved = state.last!.summary!
  expect(saved.questions).toBe(2)
  expect(saved.answered).toBe(1)
  await expect(summary).toHaveAttribute('data-session-id', String(state.last!.id))
  await expect(summary.locator('[data-summary=questions]')).toHaveText('2')
  await expect(summary.locator('[data-summary=answered]')).toHaveText('1')
  await expect(summary.locator('[data-summary=correct]')).toHaveText(`${saved.correct} su ${saved.quiz_answered}`)
})

test('recall su Telegram: avvio dal bot e interruzione dall\'app, riletti dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  await endWebSession(page, lesson.id)
  const place = page.getByRole('radiogroup', { name: 'Dove fare il recall' })

  // bot fermo: l'interruttore è disabilitato e la pagina spiega perché
  const daemon = await apiGet<{ running: boolean }>(page.request, '/telegram/daemon')
  if (daemon.running) await page.request.post('/api/v1/telegram/daemon/stop', { headers: authHeaders() })
  const settings = await apiGet<{ telegram: { chat_id?: string } }>(page.request, '/settings')
  if (!settings.telegram.chat_id) {
    await page.reload()
    await expect(place.getByRole('radio', { name: 'Telegram' })).toBeDisabled()
    await expect(page.getByText('Per il recall su Telegram configura il bot in')).toBeVisible()
    const res = await page.request.put('/api/v1/settings/telegram', {
      headers: authHeaders(),
      data: { bot_token: '123456:e2e-bot-finto', chat_id: '1' },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
  }
  await page.reload()
  await expect(place.getByRole('radio', { name: 'Telegram' })).toBeDisabled()
  await expect(page.getByText('Il bot Telegram è fermo')).toBeVisible()

  const started = await page.request.post('/api/v1/telegram/daemon/start', { headers: authHeaders() })
  expect(started.ok(), await started.text()).toBeTruthy()
  await page.reload()
  await place.getByRole('radio', { name: 'Telegram' }).click()
  await expect(page.getByTestId('place-toggle')).toContainText('Recall su Telegram')
  await page.getByRole('radiogroup', { name: 'Tipo di domanda' }).getByRole('radio', { name: 'Mirata' }).click()
  await page.getByRole('button', { name: 'Avvia su Telegram' }).click()

  const row = page.getByTestId('telegram-panel').getByTestId('telegram-session')
  await expect(row).toBeVisible({ timeout: 30_000 })
  await expect(row).toContainText('Sessione in corso su Telegram')
  await expect(row).toContainText('Mirata')
  await page.reload()
  await expect(row).toBeVisible()
  let state = await sessionState(page, lesson.id)
  expect(state.telegram?.state).toBe('active')
  await expect(row).toHaveAttribute('data-session-id', String(state.telegram!.id))
  const all = await apiGet<{ sessions: SessionInfo[] }>(page.request, '/recall/telegram')
  expect(all.sessions.map((s) => s.lesson_id)).toContain(lesson.id)

  // qui la web non pone domande mentre la sessione è su Telegram
  await place.getByRole('radio', { name: 'Qui', exact: true }).click()
  await expect(page.getByText("C'è una sessione in corso su Telegram per questa lezione")).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prossima domanda' })).toBeDisabled()

  // la sessione si vede anche dalle altre lezioni
  const other = (await apiGet<Lesson[]>(page.request, '/lessons')).find((l) => l.id !== lesson.id && l.phases.rewrite === 'VALID')
  if (other) {
    await page.goto(`/lezioni/${other.id}/recall`)
    await expect(page.locator(`[data-testid=telegram-session][data-lesson-id="${lesson.id}"]`)).toContainText('In corso su Telegram')
    await page.goto(`/lezioni/${lesson.id}/recall?luogo=telegram`)
  } else {
    await place.getByRole('radio', { name: 'Telegram' }).click()
  }

  await row.getByRole('button', { name: 'Interrompi' }).click()
  await expect(row).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Avvia su Telegram' })).toBeEnabled()
  await page.reload()
  await expect(page.getByTestId('telegram-session')).toHaveCount(0)
  state = await sessionState(page, lesson.id)
  expect(state.telegram).toBeNull()
  expect((await apiGet<{ sessions: SessionInfo[] }>(page.request, '/recall/telegram')).sessions).toEqual([])

  await page.request.post('/api/v1/telegram/daemon/stop', { headers: authHeaders() })
})
