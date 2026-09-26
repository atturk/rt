import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// RT4-F6: recall, immagini e bot Telegram contro l'API vera. Il worker gira con --mock (LLM e
// trascrizione delle risposte vocali finti) e il bot è finto (RT_TELEGRAM_FAKE=1), vedi
// scripts/e2e_server.py. Il microfono è il dispositivo finto di Chromium.
test.use({
  permissions: ['microphone'],
  launchOptions: {
    ...(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {}),
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
  },
})

type Lesson = { id: number; materia: string; phases: Record<string, string> }
type Question = { id: string; type: string; status: string; question_text: string; options?: string[] | null }
type Answer = { question_id: string; answer_text: string; is_voice: boolean; evaluation?: string | null; vote?: string | null }
type History = { questions: Question[]; answers: Answer[] }
type Overview = { questions: Record<string, Record<string, number>>; answers: number }
type Image = { name: string; url: string; in_document: boolean }

async function builtLesson(page: Page): Promise<Lesson> {
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const lesson = lessons.find((l) => l.phases.build === 'VALID')
  expect(lesson, 'la lezione di prova completata').toBeTruthy()
  return lesson!
}

async function openRecall(page: Page) {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Recall' }).click()
  await expect(page).toHaveURL(/\/recall$/)
  await page.locator(`[data-testid=picker-lesson][data-lesson-id="${lesson.id}"]`).getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/recall$`))
  return lesson
}

/** Genera la riserva se manca (i test del file condividono il server). */
async function ensureReserve(page: Page, lessonId: number) {
  const overview = await apiGet<Overview>(page.request, `/lessons/${lessonId}/recall`)
  if (Object.keys(overview.questions).length > 0) return
  await page.getByRole('button', { name: 'Genera la riserva iniziale' }).click()
  await expect(page.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded', { timeout: 30_000 })
}

async function history(page: Page, lessonId: number) {
  return apiGet<History>(page.request, `/lessons/${lessonId}/recall/history`)
}

/** Chiede la prossima domanda del tipo e aspetta che la pagina mostri quella nuova. */
async function ask(page: Page, type: 'Quiz' | 'Mirata' | 'Vasta') {
  const question = page.getByTestId('recall-question')
  const previous = (await question.count()) ? await question.getAttribute('data-question-id') : null
  await page.getByRole('radio', { name: type }).click()
  await page.getByRole('button', { name: 'Prossima domanda' }).click()
  await expect(question).toBeVisible()
  if (previous) await expect(question).not.toHaveAttribute('data-question-id', previous)
  return (await question.getAttribute('data-question-id'))!
}

test('recall: riserva, sessione quiz con voto e salto, tutto riletto dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensureReserve(page, lesson.id)
  const overview = await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)
  await page.reload()
  const quizRow = page.locator('[data-testid=reserve-row][data-type=quiz]')
  await expect(quizRow.locator('[data-status=pending]')).toHaveText(String(overview.questions.quiz?.pending ?? 0))

  const quizId = await ask(page, 'Quiz')
  await expect(page.getByTestId('recall-question')).toHaveAttribute('data-type', 'quiz')
  await page.getByTestId('recall-question').getByRole('radio').nth(1).check()
  await page.getByRole('button', { name: 'Rispondi' }).click()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  await page.getByRole('button', { name: 'Domanda utile' }).click()
  await expect(page.getByRole('button', { name: 'Domanda utile' })).toHaveAttribute('aria-pressed', 'true')

  await page.reload()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Domanda utile' })).toHaveAttribute('aria-pressed', 'true')
  let data = await history(page, lesson.id)
  const quiz = data.questions.find((q) => q.id === quizId)!
  const answer = data.answers.find((a) => a.question_id === quizId)!
  expect(quiz.status).toBe('answered')
  expect(answer.answer_text).toBe(quiz.options![1])
  expect(answer.vote).toBe('up')
  await expect(page.locator(`[data-testid=history-item][data-question-id="${quizId}"]`)).toContainText('Domanda utile')

  // Salto: la domanda torna in coda e ne arriva un'altra
  const skipped = await ask(page, 'Quiz')
  await page.getByRole('button', { name: 'Salta' }).click()
  await expect(page.getByTestId('recall-question')).not.toHaveAttribute('data-question-id', skipped)
  await page.reload()
  await expect(page.getByTestId('recall-question')).not.toHaveAttribute('data-question-id', skipped)
  data = await history(page, lesson.id)
  expect(data.questions.find((q) => q.id === skipped)!.status).toBe('pending')
})

test('recall: risposta aperta scritta valutata dal job', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensureReserve(page, lesson.id)
  const id = await ask(page, 'Mirata')
  await page.getByLabel('Risposta scritta').fill('Gli acidi grassi saturi non hanno doppi legami.')
  await page.getByRole('button', { name: 'Invia la risposta' }).click()
  await expect(page.getByTestId('recall-evaluation')).toBeVisible({ timeout: 30_000 })
  await page.reload()
  await expect(page.getByTestId('recall-answer')).toHaveText('Gli acidi grassi saturi non hanno doppi legami.')
  const answer = (await history(page, lesson.id)).answers.find((a) => a.question_id === id)!
  expect(answer.is_voice).toBe(false)
  expect(answer.evaluation).toBeTruthy()
  await expect(page.getByTestId('recall-evaluation')).toHaveText(answer.evaluation!)
})

test('recall: risposte vocali dal microfono e da un file audio', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensureReserve(page, lesson.id)

  const recorded = await ask(page, 'Vasta')
  await page.getByRole('button', { name: 'Registra' }).click()
  await expect(page.getByText('Registrazione in corso')).toBeVisible()
  await page.waitForTimeout(700)
  await page.getByRole('button', { name: 'Ferma e invia' }).click()
  await expect(page.getByTestId('recall-evaluation')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('La tua risposta (vocale, trascritta)')).toBeVisible()

  const uploaded = await ask(page, 'Mirata')
  await page.getByLabel('Carica un file audio').setInputFiles({
    name: 'risposta.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('RIFF0000WAVEfmt finto'),
  })
  await expect(page.getByTestId('recall-evaluation')).toBeVisible({ timeout: 30_000 })
  await page.reload()
  await expect(page.getByTestId('recall-evaluation')).toBeVisible()

  const answers = (await history(page, lesson.id)).answers
  for (const id of [recorded, uploaded]) {
    const answer = answers.find((a) => a.question_id === id)
    expect(answer?.is_voice, `risposta vocale a ${id}`).toBe(true)
    expect(answer?.evaluation).toBeTruthy()
  }
})

/** PDF di una pagina, abbastanza valido per PyMuPDF. */
function tinyPdf(): Buffer {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 180] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  const stream = 'BT /F1 24 Tf 40 90 Td (Slide di prova: lipidi) Tj ET'
  objects[3] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(pdf.length)
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(pdf, 'latin1')
}

test('immagini: caricamento di un PDF, avanzamento del job e anteprima nel documento', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Immagini' }).click()
  await page.locator(`[data-testid=picker-lesson][data-lesson-id="${lesson.id}"]`).getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/immagini$`))
  const before = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images

  await page.getByLabel('PDF o foto').setInputFiles({ name: 'slide.pdf', mimeType: 'application/pdf', buffer: tinyPdf() })
  await page.getByRole('button', { name: 'Aggiungi le immagini' }).click()
  await expect(page.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded', { timeout: 30_000 })

  await page.reload()
  const images = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images
  expect(images.length).toBeGreaterThan(before.length)
  await expect(page.getByTestId('lesson-image')).toHaveCount(images.length)
  for (const image of images) {
    const card = page.locator(`[data-testid=lesson-image][data-name="${image.name}"]`)
    await expect(card).toHaveAttribute('data-in-document', String(image.in_document))
    await expect(card.getByRole('img')).toHaveJSProperty('complete', true)
    expect(await card.getByRole('img').evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)
  }
  const inDocument = images.filter((i) => i.in_document)
  expect(inDocument.length).toBeGreaterThan(0)
  const preview = page.getByTestId('document-preview')
  for (const image of inDocument) {
    const img = preview.locator(`img[src="${image.url}"]`)
    await expect(img).toBeVisible()
    expect(await img.evaluate((el) => (el as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)
  }
})

test('bot Telegram: avvio e arresto del bot finto, stato riletto dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Bot Telegram' }).click()
  await expect(page).toHaveURL(/\/bot$/)
  const panel = page.getByTestId('telegram-bot')
  await expect(panel).toHaveAttribute('data-running', 'false')

  const settings = await apiGet<{ telegram: { bot_token_set?: boolean; chat_id?: string } }>(page.request, '/settings')
  if (!settings.telegram.chat_id) {
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
