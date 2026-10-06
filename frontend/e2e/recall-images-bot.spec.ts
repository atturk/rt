import { expect, type Page } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink, tinyPdf } from './support'

// Sessione di ripasso leggera, pannello Arricchimento e bot Telegram contro l'API vera. Il worker
// gira con --mock (LLM finto) e il bot è finto (RT_TELEGRAM_FAKE=1), vedi scripts/e2e_server.py.

type Lesson = { id: number; materia: string; phases: Record<string, string> }
type Question = { id: string; type: string; status: string; question_text: string; options?: string[] | null }
type Answer = { question_id: string; answer_text: string; evaluation?: string | null; outcome?: string | null; vote?: string | null }
type History = { questions: Question[]; answers: Answer[] }
type Overview = { questions: Record<string, Record<string, number>> }
type Image = { name: string; url: string; in_document: boolean }

async function builtLesson(page: Page): Promise<Lesson> {
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  // Le lezioni create dagli altri percorsi possono essere in attesa di una decisione:
  // usa la lezione completa iniziale.
  const lesson = lessons.find((l) => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')
  expect(lesson, 'la lezione di prova completata').toBeTruthy()
  return lesson!
}

const history = (page: Page, lessonId: number) => apiGet<History>(page.request, `/lessons/${lessonId}/recall/history`)

/** Genera domande del tipo dal pannello Domande se non ce ne sono da porre. */
async function ensureQuestions(page: Page, lessonId: number, type: 'quiz' | 'mirata') {
  const pending = async () => (await apiGet<Overview>(page.request, `/lessons/${lessonId}/recall`)).questions[type]?.pending ?? 0
  if ((await pending()) > 0) return
  await page.goto(`/lezioni/${lessonId}?panel=domande`)
  const panel = page.getByTestId('questions-panel')
  await panel.getByText('Genera altre domande').click()
  await panel.getByLabel('Tipo', { exact: true }).selectOption(type)
  await panel.getByRole('button', { name: 'Genera', exact: true }).click()
  await expect.poll(pending, { timeout: 30_000 }).toBeGreaterThan(0)
}

async function openSession(page: Page, lessonId: number, chip: 'Quiz' | 'Mirata') {
  await page.goto(`/lezioni/${lessonId}?panel=domande`)
  await page.getByTestId('questions-panel').getByRole('link', { name: 'Ripassa' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lessonId}/sessione$`))
  await page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: chip, exact: true }).click()
  await expect(page.getByTestId('recall-question')).toHaveAttribute('data-type', chip.toLowerCase())
}

const questionId = async (page: Page) => (await page.getByTestId('recall-question').getAttribute('data-question-id'))!

test('ripasso: quiz con esito, voto e salto', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await ensureQuestions(page, lesson.id, 'quiz')
  await openSession(page, lesson.id, 'Quiz')

  // Il clic sull'alternativa è già la risposta (4.2.2b3).
  await page.getByRole('button', { name: /^B\./ }).click()
  await expect(page.getByTestId('recall-result-card')).toBeVisible()
  const askedId = await questionId(page)
  const asked = (await history(page, lesson.id)).questions.find((q) => q.id === askedId)!
  await page.getByRole('button', { name: 'Buona domanda' }).click()
  await expect.poll(async () => (await history(page, lesson.id)).answers.find((a) => a.question_id === asked.id)?.vote).toBe('up')
  const answer = (await history(page, lesson.id)).answers.find((a) => a.question_id === asked.id)!
  expect(answer.answer_text).toBe(asked.options![1])

  // Salto: arriva un'altra domanda e quella saltata torna da porre
  await page.getByRole('button', { name: 'Prossima' }).click()
  await expect(page.getByTestId('recall-question')).not.toHaveAttribute('data-question-id', askedId)
  const skippedId = await questionId(page)
  await page.getByRole('button', { name: 'Salta' }).click()
  await expect(page.getByTestId('recall-question')).not.toHaveAttribute('data-question-id', skippedId)
  const skipped = (await history(page, lesson.id)).questions.find((q) => q.id === skippedId)!
  expect(skipped.status).toBe('pending')
})

test('ripasso: risposta aperta con la valutazione del job', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await ensureQuestions(page, lesson.id, 'mirata')
  await openSession(page, lesson.id, 'Mirata')

  const id = await questionId(page)
  await page.getByLabel('Risposta scritta').fill('Gli acidi grassi saturi non hanno doppi legami.')
  await page.getByRole('button', { name: 'Rispondi', exact: true }).click()
  const card = page.getByTestId('recall-result-card')
  await expect(card).toBeVisible({ timeout: 30_000 })
  const data = await history(page, lesson.id)
  const answer = data.answers.find((a) => a.question_id === id)!
  expect(answer.answer_text).toBe('Gli acidi grassi saturi non hanno doppi legami.')
  expect(answer.evaluation).toBeTruthy()
  await expect(card).toContainText(answer.evaluation!.trim().split('\n')[0])
})

test('arricchimento: PDF caricato dal pannello, job e immagini nella galleria', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  const before = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images
  await page.goto(`/lezioni/${lesson.id}`)
  await page.getByTestId('lesson-actions').getByRole('button', { name: 'Arricchimento' }).click()
  const panel = page.getByTestId('enrichment-panel')
  await panel.getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' }).click()
  await panel.getByLabel('PDF o foto', { exact: true }).setInputFiles({ name: 'slide.pdf', mimeType: 'application/pdf', buffer: tinyPdf() })
  await panel.getByRole('button', { name: /^Carica/ }).click()
  // Il job si segue nel pannello; finito, la galleria si aggiorna
  const count = async () => (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images.length
  await expect.poll(count, { timeout: 30_000 }).toBeGreaterThan(before.length)
  await expect.poll(async () => (await apiGet<{ state: string }[]>(page.request, `/jobs?lesson_id=${lesson.id}`)).some((j) => ['queued', 'running'].includes(j.state)), { timeout: 60_000 }).toBe(false)
  const images = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images
  await page.reload()
  const gallery = page.getByTestId('enrichment-panel').getByLabel('Media della lezione')
  await expect(gallery.getByRole('img')).toHaveCount(images.length)
  const first = gallery.getByRole('img').first()
  await expect(first).toHaveJSProperty('complete', true)
  expect(await first.evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)
})

test('bot Telegram: avvio e arresto del bot finto, stato riletto dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  // Il bot sta nella sezione Telegram delle Impostazioni (4.2.2).
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await page.getByRole('navigation', { name: 'Sezioni delle impostazioni' }).getByRole('link', { name: 'Telegram' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)
  const panel = page.getByTestId('telegram-bot')
  await expect(panel).toHaveAttribute('data-running', 'false')

  const settings = await apiGet<{ telegram: { bot_token_set?: boolean; chat_id_set?: boolean } }>(page.request, '/settings')
  if (!settings.telegram.chat_id_set) {
    // senza token e chat il backend rifiuta l'avvio: la pagina lo spiega
    await page.getByRole('button', { name: 'Avvia il bot' }).click()
    await expect(panel.getByText('Salva prima token e Chat ID del bot')).toBeVisible()
    const res = await page.request.put('/api/v1/settings/telegram', {
      headers: authHeaders(),
      data: { bot_token: '123456:e2e-bot-finto', chat_id: '1' },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
  }

  await page.getByRole('button', { name: 'Avvia il bot' }).click()
  await expect(panel).toHaveAttribute('data-running', 'true', { timeout: 15_000 })
  await page.reload()
  await expect(panel).toHaveAttribute('data-running', 'true')
  const running = await apiGet<{ running: boolean; pid: number | null }>(page.request, '/telegram/daemon')
  expect(running.running).toBe(true)
  await expect(panel.getByRole('status')).toHaveText(`Attivo (pid ${running.pid})`)

  await page.getByRole('button', { name: 'Ferma il bot' }).click()
  await expect(panel).toHaveAttribute('data-running', 'false', { timeout: 15_000 })
  await page.reload()
  await expect(panel).toHaveAttribute('data-running', 'false')
  expect((await apiGet<{ running: boolean }>(page.request, '/telegram/daemon')).running).toBe(false)
})
