import { expect, type Page } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink } from './support'

// Studio del design 4.2 (schermate 05, 05b e 06): lettura dell'unità, poi le sue domande una
// alla volta, poi l'unità dopo. Si entra dalle righe e dai gruppi di Lezioni e dall'intestazione
// della lezione; "Domande su questa parte" limita lo Studio alle unità scelte.

type Lesson = { id: number; materia: string; data: string }
type Study = { id: number; units: { id: string; title: string; questions: number; start: number | null; last_read_at: string | null; suggested_qtype: string | null }[] }

const RSVP_DEFAULT = { wpm: 300, orp: 'bilanciata', pauseMs: 400, comma: false, step: 5, size: 60, sound: false, pitch: 1, dyslexic: false, irlen: null, noise: null, noiseVolume: 0.25 }

let previousHighlighter: unknown
let previousRsvp: unknown
test.beforeEach(async ({ page }) => {
  const preferences = await apiGet<Record<string, unknown>>(page.request, '/preferences')
  previousHighlighter = preferences['study.highlighter']
  previousRsvp = preferences['study.rsvp']
  expect((await page.request.put('/api/v1/preferences/study.rsvp', { headers: authHeaders(), data: { ...RSVP_DEFAULT, sound: false } })).ok()).toBeTruthy()
  const response = await page.request.put('/api/v1/preferences/study.highlighter', {
    headers: authHeaders(), data: { color: 0, arrows: true },
  })
  expect(response.ok()).toBeTruthy()
})
test.afterEach(async ({ page }) => {
  const rsvp = previousRsvp === undefined
    ? await page.request.delete('/api/v1/preferences/study.rsvp', { headers: authHeaders() })
    : await page.request.put('/api/v1/preferences/study.rsvp', { headers: authHeaders(), data: previousRsvp })
  expect(rsvp.ok()).toBeTruthy()
  const response = previousHighlighter === undefined
    ? await page.request.delete('/api/v1/preferences/study.highlighter', { headers: authHeaders() })
    : await page.request.put('/api/v1/preferences/study.highlighter', { headers: authHeaders(), data: previousHighlighter })
  expect(response.ok()).toBeTruthy()
})

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
  await page.locator(`[data-testid=lesson-row][data-lesson-id="${l.id}"]`).locator(`a[href="/lezioni/${l.id}"]`).click()
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
  // Lo swipe segue la preferenza delle frecce: qui si accende, così il test non dipende
  // da come l'hanno lasciata gli altri (le preferenze stanno su RT, non nel browser).
  await page.request.put('/api/v1/preferences/study.highlighter', {
    headers: authHeaders(), data: { color: 0, arrows: true },
  })
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
  // touchEnd vuole l'elenco dei punti vuoto: il pointerup arriva con le coordinate dell'ultimo touchMove.
  const touch = (type: 'touchStart' | 'touchMove' | 'touchEnd' | 'touchCancel', x: number, y: number) =>
    cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] })

  // Swipe da destra a sinistra (next unit): da (300, 300) a (100, 305)
  await touch('touchStart', 300, 300)
  await page.waitForTimeout(50)
  await touch('touchMove', 200, 302)
  await page.waitForTimeout(50)
  await touch('touchMove', 100, 305)
  await touch('touchEnd', 100, 305)

  await expect(page.getByRole('heading', { level: 2 })).toContainText('Seconda Unità Mock')

  // Swipe da sinistra a destra (prev unit): da (100, 300) a (300, 305)
  await touch('touchStart', 100, 300)
  await page.waitForTimeout(50)
  await touch('touchMove', 200, 302)
  await page.waitForTimeout(50)
  await touch('touchMove', 300, 305)
  await touch('touchEnd', 300, 305)

  await expect(page.getByRole('heading', { level: 2 })).toHaveText(initialTitle)
  await context.close()
})

test('Stato di studio persistente, pulsante e S, barrette cliccabili e prima unità non appresa', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  expect(study.units).toHaveLength(2)
  const setStatus = async (uid: string, status: string) => {
    const response = await page.request.put(`/api/v1/lessons/${l.id}/study/units/${uid}`, { headers: authHeaders(), data: { status } })
    expect(response.ok()).toBeTruthy()
  }
  for (const unit of study.units) await setStatus(unit.id, 'da-imparare')
  try {
    await page.goto(`/studio/lezione/${l.id}`)
    await expect.poll(async () => (await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].last_read_at).not.toBe(study.units[0].last_read_at)
    const button = page.getByTestId('study-status')
    await expect(button).toHaveAttribute('aria-label', "Stato: da imparare")
    await button.click()
    await expect(button).toHaveAttribute('aria-label', "Stato: in apprendimento")
    await expect(button).not.toHaveAttribute('aria-disabled', 'true')
    const firstBar = page.getByTestId('study-dots').locator('button').first()
    await expect(firstBar.locator('span')).toHaveClass(/bg-study-learning/)
    await page.keyboard.press('s')
    await expect(button).toHaveAttribute('aria-label', "Stato: appresa")
    await expect(button).not.toHaveAttribute('aria-disabled', 'true')
    await expect(firstBar.locator('span')).toHaveClass(/bg-study-learned/)
    await button.click()
    await expect(button).toHaveAttribute('aria-label', 'Stato: ignorata')
    await expect(firstBar.locator('span')).toHaveClass(/bg-study-ignored/)
    await expect(button).not.toHaveAttribute('aria-disabled', 'true')
    await page.reload()
    await expect(page.getByRole('heading', { level: 2 })).toContainText('1.2')
    await firstBar.click()
    await expect(page.getByRole('heading', { level: 2 })).toContainText('1.1')
    await expect(button).toHaveAttribute('aria-label', 'Stato: ignorata')
    await page.getByTestId('unit-index-toggle').click()
    await expect(page.getByTestId('unit-index-menu').getByRole('menuitem').first()).toContainText('qui')
    await page.keyboard.press('Escape')
    await setStatus(study.units[1].id, 'appreso')
    await page.reload()
    await expect(page.getByRole('heading', { level: 2 })).toContainText('1.1')
  } finally {
    for (const unit of study.units) await setStatus(unit.id, 'da-imparare')
  }
})


test('Zen desktop e iPhone: navigazione nascosta, indice, Irlen su tutta la finestra, libro ed Esc', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto(`/studio/lezione/${l.id}`)
    await expect(page.getByTestId('study-title-button')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    const navigation = page.getByRole('navigation', { name: 'Navigazione', includeHidden: true })
    await expect(navigation).toBeVisible()
    const header = page.locator('header').first()
    const normal = await header.evaluate(el => getComputedStyle(el).backgroundColor)
    await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
    await expect(navigation).toBeHidden()
    await expect(page.getByRole('button', { name: 'Torna allo Studio', exact: true })).toBeVisible()
    await expect(page.getByTestId('highlight-tools')).toHaveCount(0)
    await expect(page.getByTestId('study-dots')).toBeHidden()
    await expect(page.getByRole('button', { name: /Giorno|Notte/ })).toHaveCount(0)
    await expect(page.getByTestId('study-quiz').or(page.getByTestId('study-generate'))).toBeHidden()
    await page.getByTestId('unit-index-toggle').click()
    await page.getByRole('menuitem').last().click()
    await expect(page.getByTestId('speed-reader-word')).toHaveText(/\S/)
    await expect(header).toContainText('1.2')
    await expect(navigation).toBeHidden()
    await page.getByRole('button', { name: 'Contesto', exact: true }).click()
    await expect(page.getByTestId('speed-reader-context')).toBeVisible()
    await page.getByRole('button', { name: 'Impostazioni della lettura veloce' }).click()
    await page.getByRole('switch', { name: 'Modalità Irlen' }).click()
    await expect(header).toHaveCSS('background-color', 'rgb(246, 220, 200)')
    await expect(page.getByTestId('speed-reader')).toHaveCSS('background-color', 'rgb(246, 220, 200)')
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#f6dcc8')
    await page.getByRole('radio', { name: 'Menta', exact: true }).click()
    await expect(header).toHaveCSS('background-color', 'rgb(213, 238, 226)')
    await page.getByRole('button', { name: 'Chiudi le impostazioni', exact: true }).click()
    const book = page.getByRole('button', { name: 'Torna allo Studio', exact: true })
    // Il libro è raggiungibile anche dalla tastiera: Spazio deve premere il pulsante.
    if (viewport.width > 767) { await book.focus(); await page.keyboard.press('Space') }
    else await book.click()
    await expect(navigation).toBeVisible()
    await expect(header).toHaveCSS('background-color', normal)
    await expect.poll(async () => ((await apiGet<Record<string, { irlen?: string }>>(page.request, '/preferences'))['study.rsvp'])?.irlen).toBe('menta')
    await expect(page.getByTestId('study-text')).toBeVisible()
    await expect(page.getByRole('heading', { level: 2 })).toContainText('1.2')
    await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
    await expect(navigation).toBeHidden()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('speed-reader')).toHaveCount(0)
    await expect(navigation).toBeVisible()
    // Il giro successivo parte dai valori iniziali, senza perdere la preferenza precedente del server.
    await page.request.put('/api/v1/preferences/study.rsvp', { headers: authHeaders(), data: { ...RSVP_DEFAULT, sound: false } })
  }
})

test('Esci porta all’unità aperta senza segnarla, anche su iPhone', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unit = study.units[1]
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto(`/studio/lezione/${l.id}`)
    await page.getByTestId('study-dots').locator('button').nth(1).click()
    await expect(page.getByRole('link', { name: 'Apri la lezione', exact: true })).toHaveCount(0)
    const link = page.getByRole('link', { name: 'Esci', exact: true })
    await expect(link).toHaveAttribute('href', `/lezioni/${l.id}#unit-${unit.id}`)
    await page.getByTestId('study-title-button').click()
    await expect(page.getByRole('link', { name: 'Apri la lezione ›' })).toHaveAttribute('href', `/lezioni/${l.id}#unit-${unit.id}`)
    await page.keyboard.press('Escape')
    await link.click()
    await expect(page).toHaveURL(new RegExp(`/lezioni/${l.id}#unit-${unit.id.replace('.', '\\.')}$`))
    const target = page.getByTestId('lesson-document').locator(`[data-unit-id="${unit.id}"]`)
    await expect(target).toBeInViewport()
    await expect(target).not.toHaveClass(/rt-claim-unit/)
  }
})

test('impostazioni zen laterali: X, Esc e icona chiudono salvando subito; su iPhone resta il foglio', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  await page.goto(`/studio/lezione/${l.id}`)
  await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
  const toggle = page.getByRole('button', { name: 'Impostazioni della lettura veloce', exact: true })
  const panel = page.getByTestId('speed-reader-settings')
  for (const close of ['X', 'Esc', 'icona']) {
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(panel).toHaveCSS('width', '340px')
    await expect(panel.getByRole('button', { name: 'Fatto' })).toHaveCount(0)
    for (const name of ['Lettura', 'Aspetto', 'Suono']) await expect(panel.getByRole('heading', { name, exact: true })).toBeVisible()
    await page.getByTestId('speed-reader-word').click()
    await expect(panel).toBeVisible()
    const request = page.waitForRequest(r => r.method() === 'PUT' && r.url().endsWith('/preferences/study.rsvp'))
    await panel.getByRole('button', { name: 'Testo più grande' }).click()
    if (close === 'X') await panel.getByRole('button', { name: 'Chiudi le impostazioni' }).click()
    else if (close === 'Esc') await page.keyboard.press('Escape')
    else await toggle.click()
    await request
    await expect(panel).toHaveCount(0)
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByTestId('speed-reader')).toBeVisible()
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await toggle.click()
  const box = await panel.boundingBox()
  expect(box!.y + box!.height).toBeCloseTo(844)
  await page.mouse.click(12, 100)
  await expect(panel).toHaveCount(0)
})

test('la formula dell’unità è resa anche nella lettura veloce e nel Contesto', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  await page.goto(`/studio/lezione/${l.id}`)
  await page.getByTestId('study-dots').locator('button').first().click()
  await expect(page.getByTestId('study-text').locator('math').first()).toBeVisible()
  await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowLeft')
  // La formula è il secondo elemento: Play la mostra prima della pausa di fine frase.
  await page.getByRole('button', { name: 'Avvia', exact: true }).click()
  await expect(page.getByTestId('speed-reader-word').locator('math')).toBeVisible()
  await page.getByRole('button', { name: 'Pausa', exact: true }).click()
  await expect(page.getByTestId('speed-reader-word')).toHaveAttribute('data-math', 'true')
  await expect(page.getByTestId('speed-reader-word').locator('.orp')).toHaveCount(0)
  await page.getByRole('button', { name: 'Contesto', exact: true }).click()
  await expect(page.getByTestId('speed-reader-context').locator('math').first()).toBeVisible()
  await page.getByRole('button', { name: 'Impostazioni della lettura veloce' }).click()
  await page.getByRole('radio', { name: 'Personalizzata', exact: true }).click()
  const slider = page.getByRole('slider', { name: 'Formule complesse' })
  await expect(slider).toHaveAttribute('min', '500')
  await expect(slider).toHaveAttribute('max', '5000')
  await expect(slider).toHaveAttribute('step', '250')
})

test('una parola evidenziata nello Studio ha la stessa fascia in zen e nel Contesto', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unitId = study.units[0].id
  const previous = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)
  try {
    await page.goto(`/studio/lezione/${l.id}`)
    const text = page.getByTestId('study-text')
    await expect(text).toHaveText(/\S.{40,}/)
    await text.evaluate(root => {
      const node = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: n => (n.textContent ?? '').trim().length > 12 ? 1 : 3 }).nextNode()!
      const range = document.createRange()
      const start = node.textContent!.search(/\S/)
      range.setStart(node, start); range.setEnd(node, start + 10)
      getSelection()!.removeAllRanges(); getSelection()!.addRange(range)
      root.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    })
    await expect(text.locator('.rt-hl').first()).toBeVisible()
    await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
    const word = page.getByTestId('speed-reader-word')
    await expect(word).toHaveAttribute('data-hl', 'true')
    const bg = await word.locator('.orp').evaluate(el => getComputedStyle(el).backgroundColor)
    expect(bg).not.toBe('rgba(0, 0, 0, 0)')
    await expect(word.locator('.pre > span')).toHaveCSS('background-color', bg)
    await expect(word.locator('.post > span')).toHaveCSS('background-color', bg)
    await page.getByRole('button', { name: 'Contesto', exact: true }).click()
    await expect(page.getByTestId('speed-reader-context').locator('.rt-rsvp-hl').first()).toHaveCSS('background-color', bg)
    await page.getByRole('button', { name: 'Impostazioni della lettura veloce' }).click()
    await page.getByRole('switch', { name: 'Mostra le evidenziazioni' }).click()
    await expect(word).not.toHaveAttribute('data-hl')
  } finally {
    const rows = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)
    for (const row of rows.filter(row => !previous.some(old => old.id === row.id))) {
      await page.request.delete(`/api/v1/lessons/${l.id}/highlights/${row.id}`, { headers: authHeaders() })
    }
  }
})

test('quattro pulsanti tondi uguali: Genera diventa Ripassa e apre le domande dell’unità', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unit = study.units[0]
  expect(unit.questions).toBe(0)
  await page.goto(`/studio/lezione/${l.id}`)
  await page.getByTestId('study-dots').locator('button').first().click()
  await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
  const controls = page.getByTestId('speed-reader-controls')
  await expect(controls.getByRole('button')).toHaveCount(4)
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 })
    const size = width === 390 ? 48 : 56
    for (const button of await controls.getByRole('button').all()) {
      await expect(button).toHaveCSS('width', `${size}px`)
      await expect(button).toHaveCSS('height', `${size}px`)
      expect(await button.evaluate(el => parseFloat(getComputedStyle(el).borderRadius))).toBeGreaterThanOrEqual(size / 2)
    }
  }
  await page.setViewportSize({ width: 1280, height: 844 })
  await page.getByRole('button', { name: 'Genera domande su questa unità' }).click()
  const modal = page.getByTestId('study-generate-modal')
  await expect(modal).toBeVisible()
  const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/lessons/${l.id}/recall/generate`))
  await modal.getByRole('button', { name: 'Genera', exact: true }).click()
  expect((await request).postDataJSON()).toMatchObject({ unit_ids: [unit.id] })
  await expect(modal).toBeHidden({ timeout: 90_000 })
  const review = page.getByRole('button', { name: /Ripassa l'unità · \d+ domande/ })
  await expect(review).toBeVisible()
  await review.click()
  await expect(page.getByTestId('speed-reader')).toBeHidden()
  await expect(page.getByTestId('recall-session-page')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(unit.title)
  await expect(page.getByTestId('recall-question')).toHaveAttribute('data-type', 'quiz')
  await expect(page.getByRole('navigation', { name: 'Navigazione' })).toBeVisible()
})


test('ai limiti le frecce lasciano l’unità aperta e mostrano la fascia', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  await page.goto(`/studio/lezione/${l.id}`)
  await page.getByTestId('study-dots').locator('button').first().click()
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByTestId('study-edge-left')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2 })).toContainText(study.units[0].title)
  await page.getByTestId('study-dots').locator('button').last().click()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('study-edge-right')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2 })).toContainText(study.units.at(-1)!.title)
  await expect(page.getByTestId('study-done')).toHaveCount(0)
  await expect(page.locator('[aria-live="polite"]')).toContainText('Ultima unità')
})

test('swipe ai limiti a 390 px: fascia e unità invariata', async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 390, height: 844 } })
  const page = await context.newPage()
  try {
    await loginViaLink(page)
    const l = await lesson(page, 'STUDIO')
    await page.goto(`/studio/lezione/${l.id}`)
    const cdp = await context.newCDPSession(page)
    for (const side of ['left', 'right']) {
      const buttons = page.getByTestId('study-dots').locator('button')
      await (side === 'left' ? buttons.first() : buttons.last()).click()
      await expect(page.getByRole('heading', { level: 2 })).toContainText(side === 'left' ? '1.1' : '1.2')
      const title = await page.getByRole('heading', { level: 2 }).textContent()
      const start = side === 'left' ? 100 : 300
      const end = side === 'left' ? 300 : 100
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: start, y: 400 }] })
      await page.waitForTimeout(50) // Distanzia i campioni del gesto, come uno swipe reale.
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: (start + end) / 2, y: 402 }] })
      await page.waitForTimeout(50)
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: end, y: 405 }] })
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
      await expect(page.getByTestId(`study-edge-${side}`)).toBeVisible()
      await expect(page.getByRole('heading', { level: 2 })).toHaveText(title!)
      await expect(page.getByTestId('study-done')).toHaveCount(0)
      await expect(page.getByTestId(`study-edge-${side}`)).toHaveCount(0)
    }
  } finally { await context.close() }
})

test('finite le domande dell’ultima unità: Genera consigliato con Quante 2 riprende la sessione', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  await page.setViewportSize({ width: 390, height: 844 })
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unit = study.units.at(-1)!
  const selection = await apiGet<{ custom: boolean; units: { unit_id: string; selected: boolean }[] }>(page.request, `/lessons/${l.id}/recall/units`)
  // Il rifornimento automatico della lezione resta sulle altre unità: questa deve esaurirsi davvero.
  expect((await page.request.put(`/api/v1/lessons/${l.id}/recall/units`, {
    headers: authHeaders(), data: { unit_ids: study.units.filter(u => u.id !== unit.id).map(u => u.id) },
  })).ok()).toBeTruthy()
  try {
    const history = await apiGet<{ questions: { id: string; unit_ids: string[] }[] }>(page.request, `/lessons/${l.id}/recall/history`)
    for (const question of history.questions.filter(q => q.unit_ids.includes(unit.id))) {
      expect((await page.request.post(`/api/v1/lessons/${l.id}/recall/questions/${question.id}/status`, {
        headers: authHeaders(), data: { status: 'asked' },
      })).ok()).toBeTruthy()
    }
    const accepted = await page.request.post(`/api/v1/lessons/${l.id}/recall/generate`, {
      headers: authHeaders(), data: { qtype: 'consigliato', unit_ids: [unit.id], count: 1 },
    })
    const jobId = (await accepted.json()).job_id
    await expect.poll(async () => (await apiGet<{ state: string }>(page.request, `/jobs/${jobId}`)).state).toBe('succeeded')
    await page.goto(`/studio/lezione/${l.id}`)
    await page.getByTestId('study-dots').locator('button').last().click()
    await page.getByTestId('study-quiz').click()
    await answer(page)
    await page.getByRole('button', { name: 'Fine', exact: true }).click()
    await expect(page.getByTestId('recall-empty')).toBeVisible()
    await expect(page.getByTestId('recall-unit-done')).toHaveCount(0)
    const generation = page.getByTestId('recall-empty-generation')
    await expect(generation.getByRole('button', { name: 'Genera', exact: true })).toBeVisible()
    for (const button of await generation.getByRole('button').all()) {
      const box = await button.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(390)
      expect(await button.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
    await page.getByLabel('Quante', { exact: true }).fill('2')
    const request = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/lessons/${l.id}/recall/generate`))
    await page.getByRole('button', { name: 'Genera', exact: true }).click()
    expect((await request).postDataJSON()).toMatchObject({ qtype: unit.suggested_qtype, count: 2, unit_ids: [unit.id] })
    await expect(page.getByTestId('recall-question')).toBeVisible({ timeout: 45_000 })
    await expect(page.getByTestId('recall-empty')).toHaveCount(0)
  } finally {
    expect((await page.request.put(`/api/v1/lessons/${l.id}/recall/units`, {
      headers: authHeaders(), data: { unit_ids: selection.custom ? selection.units.filter(u => u.selected).map(u => u.unit_id) : null },
    })).ok()).toBeTruthy()
  }
})

test('a 390 px un’impostazione si divide e resta dentro la finestra', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/studio/lezione/${l.id}`)
  await page.getByTestId('study-dots').locator('button').first().click()
  await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
  await page.keyboard.press('ArrowRight')
  const word = page.getByTestId('speed-reader-word')
  await expect(word).toContainText('imposta')
  expect(Number(await word.getAttribute('data-scale'))).toBeGreaterThanOrEqual(.7)
  for (const fragment of await word.locator('.pre > span, .orp, .post > span').all()) {
    const box = await fragment.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(390)
  }
  await page.getByRole('button', { name: 'Contesto', exact: true }).click()
  await expect(page.getByTestId('speed-reader-context')).toContainText('un’impostazione')
  await expect(page.getByTestId('speed-reader-context')).not.toContainText('imposta-')
})

test('il clic destro toglie un’evidenziazione salvata anche dopo il ricaricamento', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unitId = study.units[0].id
  const previous = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)
  try {
    await page.goto(`/studio/lezione/${l.id}`)
    await page.getByTestId('study-dots').locator('button').first().click()
    const text = page.getByTestId('study-text')
    await expect(text).toHaveText(/\S.{40,}/)
    await text.evaluate(root => {
      const node = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: n => (n.textContent ?? '').trim().length > 12 ? 1 : 3 }).nextNode()!
      const range = document.createRange()
      const start = node.textContent!.search(/\S/)
      range.setStart(node, start); range.setEnd(node, start + 10)
      getSelection()!.removeAllRanges(); getSelection()!.addRange(range)
      root.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    })
    await expect.poll(async () => (await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)).length).toBe(previous.length + 1)
    await text.locator('.rt-hl').first().click({ button: 'right' })
    await expect.poll(async () => (await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)).length).toBe(previous.length)
    await page.reload()
    await page.getByTestId('study-dots').locator('button').first().click()
    await expect(text.locator('.rt-hl')).toHaveCount(previous.length)
  } finally {
    const rows = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=${unitId}`)
    for (const row of rows.filter(row => !previous.some(old => old.id === row.id))) await page.request.delete(`/api/v1/lessons/${l.id}/highlights/${row.id}`, { headers: authHeaders() })
  }
})

test('Vai all’unità dalla lezione continua a segnare il testo', async ({ page }) => {
  await loginViaLink(page)
  const l = await lesson(page, 'STUDIO')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  const unit = study.units[1]
  await page.goto(`/lezioni/${l.id}#unit-${unit.id}`)
  const target = page.getByTestId('lesson-document').locator(`[data-unit-id="${unit.id}"]`)
  await expect(target).toBeInViewport()
  await expect(target).toHaveClass(/rt-claim-unit/)
})
