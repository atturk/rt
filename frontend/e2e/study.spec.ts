import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// Studio del design 4.2 (schermate 05, 05b e 06): lettura dell'unità, poi le sue domande una
// alla volta, poi l'unità dopo. Si entra dalle righe e dai gruppi di Lezioni e dall'intestazione
// della lezione; "Domande su questa parte" limita lo Studio alle unità scelte.

type Lesson = { id: number; materia: string; data: string }
type Study = { id: number; units: { id: string; title: string; questions: number; start: number | null }[] }

async function lesson(page: Page, materia: string) {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

/** Risponde alla domanda mostrata: la prima alternativa del quiz, o un testo per le aperte.
 *  Dalla 4.2.2b3 le domande dello Studio sono la sessione di ripasso vera e propria. */
async function answer(page: Page) {
  const question = page.getByTestId('recall-question')
  await expect(question).toBeVisible()
  if ((await question.getAttribute('data-type')) === 'quiz') {
    // Il clic sull'alternativa è già la risposta, e il microfono c'è solo nelle aperte.
    await expect(page.getByRole('button', { name: 'Rispondi a voce' })).toHaveCount(0)
    await question.getByRole('button', { name: /^A\./ }).click()
  } else {
    await question.getByLabel('Risposta scritta').fill('Risposta di prova scritta nello Studio.')
    await question.getByRole('button', { name: 'Rispondi', exact: true }).click()
  }
  await expect(page.getByTestId('recall-result-card')).toBeVisible({ timeout: 45_000 })
}

test('Studio di una lezione dalla pagina della lezione: lettura, domande generate per la parte, ripasso dell’unità', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  expect(study.units.length).toBeGreaterThan(0)
  const first = study.units[0]

  // Dalla riga si apre la lezione, Studio è nell'intestazione.
  await page.goto('/')
  await page.locator(`[data-testid=lesson-row][data-lesson-id="${l.id}"]`).getByRole('link').click()
  await page.getByTestId('lesson-actions').getByRole('link', { name: 'Studio' }).click()
  await expect(page).toHaveURL(new RegExp(`/studio/lezione/${l.id}$`))

  // Lettura (schermata 05): trattini, dove sei, testo dell'unità, audio dei suoi timecode.
  if (study.units.length > 1) await expect(page.getByTestId('unit-index-toggle')).toContainText(`Unità 1 di ${study.units.length}`)
  await expect(page.getByRole('heading', { level: 1 })).not.toContainText('unità 1 di')
  await expect(page.getByTestId('study-dots').locator('> *')).toHaveCount(study.units.length)
  await expect(page.getByTestId('study-text')).toHaveText(/\S.{40,}/)
  await expect(page.getByRole('button', { name: 'Audio della lezione per questa unità' })).toBeVisible()
  await page.getByTestId('study-audio').evaluate((a: HTMLAudioElement) => (a.muted = true))
  await page.getByRole('button', { name: 'Audio della lezione per questa unità' }).click()
  await expect(page.getByRole('button', { name: "Ferma l'audio dell'unità" })).toBeVisible()
  await expect
    .poll(() => page.getByTestId('study-audio').evaluate((a: HTMLAudioElement) => a.currentTime))
    .toBeGreaterThanOrEqual(first.start ?? 0)
  await page.getByRole('button', { name: "Ferma l'audio dell'unità" }).click()
  // Senza domande sull'unità si generano sul posto (4.2.2b3).
  if (first.questions === 0) {
    await expect(page.getByTestId('study-generate')).toContainText('Nessuna domanda · genera ora')
  }

  // "Domande su questa parte": lo Studio della prima unità, con le domande da generare.
  await page.goto(`/studio/lezione/${l.id}?unita=${first.id}`)
  await expect(page.getByTestId('study-no-questions')).toContainText(first.id)
  const generated = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith(`/lessons/${l.id}/recall/generate`))
  await page.getByRole('button', { name: 'Genera le domande' }).click()
  expect((await generated).postDataJSON()).toMatchObject({ unit_ids: [first.id] })
  // Generate le domande, la parte parte subito dal ripasso dell'unità.
  await expect(page.getByTestId('recall-session-page')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('heading', { level: 1 })).toContainText(first.title)
  expect((await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].questions).toBeGreaterThan(0)

  // Lo Studio della lezione intera: lettura e poi "Mettimi alla prova · N" (4.2.2b4 F2).
  await page.goto(`/studio/lezione/${l.id}`)
  const quiz = page.getByTestId('study-quiz')
  await expect(quiz).toHaveText(/^Mettimi alla prova · \d+$/)
  await expect(page.getByTestId('study-generate')).toBeVisible()
  await expect.poll(async () => {
    const text = await quiz.textContent()
    const current = Number(text?.match(/(\d+)/)?.[1] ?? -1)
    const pending = (await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].questions
    if (current !== pending) {
      await page.reload()
      return -1
    }
    return current
  }).toBeGreaterThan(0)
  const total = Number((await quiz.textContent())!.match(/(\d+)/)![1])
  await quiz.click()
  // La sessione dell'unità: chip per tipo, ritorno al testo dall'icona in alto a destra.
  await expect(page.getByTestId('recall-session-page')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Vasta', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Torna allo studio' }).first().click()
  await expect(page.getByTestId('study-text')).toBeVisible()
  await page.getByTestId('study-quiz').click()
  await expect(page.getByTestId('recall-question')).toBeVisible()
  // Due risposte, poi "Termina" riporta al testo dell'unità con le domande rimaste.
  const answers = Math.min(2, total)
  const answered: string[] = []
  for (let i = 0; i < answers; i++) {
    const current = (await page.getByTestId('recall-question').getAttribute('data-question-id'))!
    answered.push(current)
    await answer(page)
    if (i + 1 < answers) {
      await page.getByRole('button', { name: 'Prossima' }).click()
      await expect(page.getByTestId('recall-question')).not.toHaveAttribute('data-question-id', current)
    }
  }
  // Le risposte sono registrate e "Termina" riporta al testo dell'unità.
  const history = await apiGet<{ answers: { question_id: string }[] }>(page.request, `/lessons/${l.id}/recall/history`)
  for (const id of answered) expect(history.answers.map((a) => a.question_id)).toContain(id)
  await page.getByRole('button', { name: 'Termina' }).click()
  await expect(page.getByTestId('study-text')).toBeVisible()
  await expect(page.getByTestId('study-quiz')).toContainText('Mettimi alla prova')
})

test('Studio dall\'intestazione della lezione; telefono', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'BIOCHIMICA')

  // Intestazione della lezione: Studio (Recall accanto porta subito alle domande).
  await page.goto(`/lezioni/${l.id}`)
  await page.getByTestId('lesson-actions').getByRole('link', { name: 'Studio' }).click()
  await expect(page).toHaveURL(new RegExp(`/studio/lezione/${l.id}$`))

  // Telefono: colonna a tutta larghezza e pulsante in basso sempre a portata.
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByTestId('study-text')).toBeVisible()
  const footer = page.getByTestId('study-quiz').or(page.getByTestId('study-generate')).first()
  await expect(footer).toBeInViewport()
  const box = (await footer.boundingBox())!
  expect(box.height).toBeGreaterThanOrEqual(44)
  expect(box.width).toBeGreaterThan(250)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('A2: altezza intestazione su Lezioni, Studio e Ripasso (desktop e 390px) e centratura StatusDot', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')

  for (const viewport of [{ width: 1280, height: 800, expected: 52 }, { width: 390, height: 844, expected: 64 }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })

    // 1. Pagina Lezioni (/)
    await page.goto('/')
    const lessonsHeader = page.locator('header').first()
    await expect(lessonsHeader).toBeVisible()
    const lBox = (await lessonsHeader.boundingBox())!
    expect(Math.abs(lBox.height - viewport.expected)).toBeLessThanOrEqual(2)

    // Misura centro del pallino contro centro della prima riga del titolo
    const row = page.locator(`[data-testid=lesson-row][data-lesson-id="${l.id}"]`)
    await expect(row).toBeVisible()
    const dot = row.getByTestId('lesson-status')
    await expect(dot).toBeVisible()
    const dotBox = (await dot.boundingBox())!
    const dotCenterY = dotBox.y + dotBox.height / 2

    const titleCenterY = await row.locator('span.text-body').first().evaluate((el) => {
      const range = document.createRange()
      range.selectNodeContents(el.firstChild || el)
      const rects = range.getClientRects()
      const firstRect = rects.length > 0 ? rects[0] : el.getBoundingClientRect()
      return firstRect.y + firstRect.height / 2
    })
    expect(Math.abs(dotCenterY - titleCenterY)).toBeLessThanOrEqual(2)

    // 2. Pagina Studio (/studio/lezione/:id)
    await page.goto(`/studio/lezione/${l.id}`)
    const studyHeader = page.locator('header').first()
    await expect(studyHeader).toBeVisible()
    const sBox = (await studyHeader.boundingBox())!
    expect(Math.abs(sBox.height - viewport.expected)).toBeLessThanOrEqual(2)

    // 3. Pagina Ripasso (/lezioni/:id/sessione)
    await page.goto(`/lezioni/${l.id}/sessione`)
    const recallHeader = page.locator('header').first()
    await expect(recallHeader).toBeVisible()
    const rBox = (await recallHeader.boundingBox())!
    expect(Math.abs(rBox.height - viewport.expected)).toBeLessThanOrEqual(2)

    // Esci nel ripasso è sola freccia indietro con label "Esci"
    const backBtn = recallHeader.getByRole('link', { name: 'Esci' })
    await expect(backBtn).toBeVisible()
  }
})

test('Evidenziatore dello Studio: si salva su RT, torna alla riapertura, la gomma lo toglie', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  await page.goto(`/studio/lezione/${l.id}`)
  const text = page.getByTestId('study-text')
  await expect(text).toHaveText(/\S.{40,}/)
  // Selezione delle prime parole del primo paragrafo, come col mouse.
  const selected = await text.evaluate((root) => {
    const node = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.textContent ?? '').trim().length > 12 ? 1 : 3 }).nextNode()!
    const range = document.createRange()
    const start = node.textContent!.search(/\S/)
    range.setStart(node, start)
    range.setEnd(node, start + 10)
    getSelection()!.removeAllRanges()
    getSelection()!.addRange(range)
    const chosen = range.toString()
    root.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    return chosen
  })
  await expect(text.locator('.rt-hl')).toHaveText(selected)
  await expect(text.locator('.rt-hl-0')).toHaveCount(1)
  await expect.poll(async () => (await apiGet<unknown[]>(page.request, `/lessons/${l.id}/highlights?unit=${(await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].id}`)).length).toBe(1)

  await page.reload()
  await expect(text.locator('.rt-hl')).toHaveText(selected)
  await page.getByTestId('highlight-eraser').click()
  await text.locator('.rt-hl').first().click()
  await expect(text.locator('.rt-hl')).toHaveCount(0)
  await page.reload()
  await expect(text).toHaveText(/\S.{40,}/)
  await expect(text.locator('.rt-hl')).toHaveCount(0)
})

test('Lettura veloce dallo Studio: parola con la lettera di fuoco, pausa con il testo intorno, Esc torna', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  await page.goto(`/studio/lezione/${l.id}`)
  await expect(page.getByTestId('study-text')).toHaveText(/\S.{40,}/)
  await page.getByRole('button', { name: 'Lettura veloce' }).click()
  const reader = page.getByTestId('speed-reader')
  await expect(reader).toBeVisible()
  const word = page.getByTestId('speed-reader-word')
  const first = await word.textContent()
  expect(first?.trim().length).toBeGreaterThan(0)
  await page.keyboard.press('Space')
  await expect(word).not.toHaveText(first!)
  await expect(page.getByTestId('speed-reader-after')).toBeEmpty()
  await page.keyboard.press('Space')
  await expect(page.getByTestId('speed-reader-count')).toContainText('parole')
  await page.keyboard.press('Escape')
  await expect(reader).toHaveCount(0)
  await expect(page.getByTestId('study-text')).toBeVisible()
})

test('Swipe touch fra le unità dello Studio sul telefono (4.2.2b4 F1)', async ({ browser }) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 844 },
  })
  const page = await context.newPage()
  await loginViaLink(page)
  const l = await lesson(page, 'BIOCHIMICA')

  await page.route(`**/api/v1/lessons/${l.id}/study`, async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    if (json.units && json.units.length === 1) {
      json.units.push({
        ...json.units[0],
        id: 'mock-unit-2',
        title: 'Seconda Unità Mock',
        html: '<p>Testo della seconda unità.</p>',
      })
    }
    await route.fulfill({ response, json })
  })

  await page.goto(`/studio/lezione/${l.id}`)
  await expect(page.getByTestId('study-text')).toBeVisible()

  const unitHeading = page.getByRole('heading', { level: 2 })
  await expect(unitHeading).toBeVisible()
  const initialTitle = (await unitHeading.textContent()) ?? ''

  const cdp = await page.context().newCDPSession(page)
  const touch = (type: 'touchStart' | 'touchMove' | 'touchEnd' | 'touchCancel', x: number, y: number) =>
    cdp.send('Input.dispatchTouchEvent', { type, touchPoints: [{ x, y }] })

  // Swipe da destra a sinistra (next unit): da (300, 300) a (100, 305)
  await touch('touchStart', 300, 300)
  await page.waitForTimeout(50)
  await touch('touchMove', 200, 302)
  await page.waitForTimeout(50)
  await touch('touchEnd', 100, 305)

  await expect(page.getByRole('heading', { level: 2 })).toContainText('Seconda Unità Mock')

  // Swipe da sinistra a destra (prev unit): da (100, 300) a (300, 305)
  await touch('touchStart', 100, 300)
  await page.waitForTimeout(50)
  await touch('touchMove', 200, 302)
  await page.waitForTimeout(50)
  await touch('touchEnd', 300, 305)

  await expect(page.getByRole('heading', { level: 2 })).toHaveText(initialTitle)
  await context.close()
})

