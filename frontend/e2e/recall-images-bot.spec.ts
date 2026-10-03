import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink, openLessonDetails, scrollDocumentTo, tinyPdf } from './support'

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
  // Le immagini aggiunte da un test precedente rendono da rifare il documento (RT4-FA2).
  // Le lezioni create durante gli altri percorsi possono essere in attesa di una decisione;
  // usa la lezione completa iniziale invece di prendere la prima per data.
  const lesson = lessons.find((l) => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')
  expect(lesson, 'la lezione di prova completata').toBeTruthy()
  return lesson!
}

async function openRecall(page: Page) {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.goto('/recall')
  await page.locator(`[data-testid=picker-lesson][data-lesson-id="${lesson.id}"]`).getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/recall$`))
  return lesson
}

/** Genera il pool se manca (i test del file condividono il server). */
async function ensurePool(page: Page, lessonId: number) {
  const overview = await apiGet<Overview>(page.request, `/lessons/${lessonId}/recall`)
  if (Object.keys(overview.questions).length > 0) return
  await page.getByRole('button', { name: 'Genera il pool' }).click()
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

test('recall: pool, sessione quiz con voto e salto, tutto riletto dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensurePool(page, lesson.id)
  const overview = await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)
  await page.reload()
  const quizRow = page.locator('[data-testid=pool-row][data-type=quiz]')
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
  await ensurePool(page, lesson.id)
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

test('recall del giorno: raggruppa per giorno e apre la sessione sulle lezioni di quella data', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  const { data } = lesson as unknown as { data: string }
  await page.goto('/recall')
  await page.getByLabel('Raggruppa per').selectOption('giorno')
  await page.locator(`[data-testid=recall-subject][data-subject="${data}"]`).getByTestId('subject-recall').click()
  await expect(page).toHaveURL(new RegExp(`/recall/giorno/${data}$`))
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Recall del giorno')
  await expect(page.locator(`[data-testid=subject-lesson][data-lesson-id="${lesson.id}"]`)).toBeVisible()
  await page.goto('/recall')
  await page.getByLabel('Raggruppa per').selectOption('materia')
})

test('recall della materia: domande dalle lezioni della materia, risposta e riepilogo', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.goto('/recall')
  await page.locator('[data-testid=recall-subject][data-subject=BIOCHIMICA]').getByTestId('subject-recall').click()
  await expect(page).toHaveURL(/\/recall\/materie\/BIOCHIMICA$/)
  await expect(page.locator(`[data-testid=subject-lesson][data-lesson-id="${lesson.id}"]`)).toBeVisible()
  const generate = page.getByRole('button', { name: /Genera le domande mancanti/ })
  if (await generate.isVisible()) {
    await generate.click()
    for (const job of await page.getByTestId('job-progress').all()) {
      await expect(job).toHaveAttribute('data-state', 'succeeded', { timeout: 30_000 })
    }
  }

  const id = await ask(page, 'Quiz')
  const question = page.getByTestId('recall-question')
  const lessonId = Number(await question.getAttribute('data-lesson-id'))
  await expect(page.getByTestId('question-lesson')).toHaveAttribute('href', `/lezioni/${lessonId}`)
  await question.getByRole('radio').nth(1).check()
  await page.getByRole('button', { name: 'Rispondi' }).click()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('recall-result')).toBeVisible()
  expect((await history(page, lessonId)).answers.some((a) => a.question_id === id)).toBe(true)
  await expect(page.getByTestId('subject-session')).toContainText('domande poste: 1')

  await page.getByRole('button', { name: 'Termina sessione' }).click()
  await expect(page.getByTestId('session-summary')).toBeVisible()
  await expect(page.getByTestId('session-summary').locator('[data-summary=answered]')).toHaveText('1')
})

test('recall: risposte vocali dal microfono e da un file audio', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensurePool(page, lesson.id)

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

test('recall: unità per il recaller e domande eliminate in blocco, rilette dopo la ricarica', async ({ page }) => {
  const lesson = await openRecall(page)
  await ensurePool(page, lesson.id)
  await page.getByTestId('unit-selector').locator('summary').click()
  await expect(page.getByTestId('recall-unit').first()).toBeVisible()

  await page.getByTestId('questions-link').click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/recall/domande$`))
  const before = (await history(page, lesson.id)).questions.length
  const items = page.getByTestId('question-item')
  await expect(items).toHaveCount(before)
  const doomed = [await items.nth(0).getAttribute('data-question-id'), await items.nth(1).getAttribute('data-question-id')]
  await items.nth(0).getByRole('checkbox').click()
  await items.nth(1).getByRole('checkbox').click({ modifiers: ['Shift'] })
  await page.getByRole('button', { name: /Elimina selezionate \(2\)/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Elimina' }).click()
  await expect(items).toHaveCount(before - 2)
  await page.reload()
  await expect(items).toHaveCount(before - 2)
  const left = new Set((await history(page, lesson.id)).questions.map((q) => q.id))
  for (const id of doomed) expect(left.has(id!), `domanda ${id} eliminata`).toBe(false)
})

test('immagini: caricamento di un PDF, avanzamento del job e anteprima nel documento', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.goto('/arricchimento')
  await page.locator(`[data-testid=picker-lesson][data-lesson-id="${lesson.id}"]`).getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/arricchimento$`))
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

  // Anche la pagina della lezione mostra le immagini nel documento, e porta a recall e immagini
  await page.goto(`/lezioni/${lesson.id}`)
  const docImage = page.getByTestId('lesson-document').locator(`img[src="${inDocument[0].url}"]`)
  await scrollDocumentTo(page, docImage)
  await expect(docImage).toBeVisible()
  expect(await docImage.evaluate((el) => (el as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)
  await openLessonDetails(page)
  await page.getByTestId('lesson-links').getByRole('link', { name: 'Recall' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}/recall$`))
})

test('immagini: N immagini per unità dal web sulle unità scelte, riletto dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await builtLesson(page)
  await page.goto(`/lezioni/${lesson.id}/immagini`)
  const before = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images
  const outline = await apiGet<{ macro_sections: { id: string; title: string; units: { id: string }[] }[] }>(
    page.request,
    `/lessons/${lesson.id}/outline`,
  )
  const section = outline.macro_sections[0]

  // il campo si svuota e non diventa "03"
  const count = page.getByLabel('Immagini per unità')
  await expect(count).toHaveValue('0')
  // cursore dopo lo 0 (su macOS il tasto Fine non lo sposta nei campi di testo)
  await count.focus()
  await count.evaluate((el: HTMLInputElement) => el.setSelectionRange(el.value.length, el.value.length))
  await count.pressSequentially('3')
  await expect(count).toHaveValue('3')
  await count.fill('')
  await expect(count).toHaveValue('')
  await count.pressSequentially('11')
  await page.getByRole('button', { name: 'Aggiungi le immagini' }).click()
  await expect(page.getByText('Scrivi un numero da 0 a 10.')).toBeVisible()
  await count.fill('2')

  await expect(page.getByLabel('Tutte le unità')).toBeChecked()
  await page.getByLabel('Scegli le unità').check()
  await page.getByRole('button', { name: 'Aggiungi le immagini' }).click()
  await expect(page.getByText("Scegli almeno un'unità")).toBeVisible()
  await page.getByLabel(`Seleziona sezione ${section.id}. ${section.title}`).check()
  for (const unit of section.units) await expect(page.getByTestId('unit-picker').locator(`[data-unit-id="${unit.id}"]`)).toBeChecked()
  await expect(page.getByText(`Unità scelte: ${section.units.length}`)).toBeVisible()
  await page.getByRole('button', { name: 'Aggiungi le immagini' }).click()
  await expect(page.getByTestId('job-progress')).toHaveAttribute('data-state', 'succeeded', { timeout: 30_000 })

  const jobId = new URL(page.url()).searchParams.get('job')!
  await page.reload()
  const job = await apiGet<{ payload: Record<string, unknown>; result: Record<string, unknown> }>(page.request, `/jobs/${jobId}`)
  const chosen = section.units.map((u) => u.id)
  expect(job.payload.unit_ids).toEqual(chosen)
  expect(job.payload.web_search_count).toBe(2)
  expect(job.payload).not.toHaveProperty('carousel')
  expect(job.result.web_images_by_unit).toEqual(Object.fromEntries(chosen.map((id) => [id, 2])))
  const images = (await apiGet<{ images: Image[] }>(page.request, `/lessons/${lesson.id}/images`)).images
  expect(images.length).toBe(before.length + 2 * chosen.length)
  await expect(page.getByTestId('lesson-image')).toHaveCount(images.length)
  await expect(page.getByText('carosello')).toHaveCount(0)
})

test('bot Telegram: avvio e arresto del bot finto, stato riletto dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  // Il bot sta nelle Impostazioni (design 4.2).
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await page.getByRole('navigation', { name: 'Sezioni delle impostazioni' }).getByRole('link', { name: 'Bot Telegram' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/bot$/)
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
