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

/** Risponde alla domanda mostrata: la prima risposta del quiz, o un testo per le aperte. */
async function answer(page: Page) {
  const question = page.getByTestId('study-question')
  await expect(question).toBeVisible()
  if ((await question.getAttribute('data-type')) === 'quiz') {
    // Il microfono c'è solo nelle domande aperte.
    await expect(page.getByRole('button', { name: 'Rispondi a voce' })).toHaveCount(0)
    await question.getByRole('group', { name: 'Risposte' }).getByRole('button').first().click()
    await expect(page.getByTestId('study-feedback')).toContainText(/Giusto|Sbagliato/)
    await expect(question.locator('[data-state=correct]')).toHaveCount(1)
  } else {
    await question.getByLabel('La tua risposta').fill('Risposta di prova scritta nello Studio.')
    await question.getByRole('button', { name: 'Invia la risposta' }).click()
    await expect(page.getByTestId('study-feedback')).toBeVisible({ timeout: 45_000 })
  }
}

test('Studio di una lezione dalla riga di Lezioni: lettura, domande generate per la parte, unità dopo', async ({ page }) => {
  test.setTimeout(150_000)
  await loginViaLink(page)
  const l = await lesson(page, 'PATOLOGIA')
  const study = await apiGet<Study>(page.request, `/lessons/${l.id}/study`)
  expect(study.units.length).toBeGreaterThan(0)
  const first = study.units[0]

  // Dalla riga della lezione.
  await page.goto('/')
  await page.locator(`[data-testid=lesson-row][data-lesson-id="${l.id}"]`).getByRole('link', { name: 'Studio' }).click()
  await expect(page).toHaveURL(new RegExp(`/studio/lezione/${l.id}$`))

  // Lettura (schermata 05): trattini, dove sei, testo dell'unità, audio dei suoi timecode.
  await expect(page.getByRole('heading', { level: 1 })).toContainText(`unità 1 di ${study.units.length}`)
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
  // Senza domande sull'unità si va avanti.
  if (first.questions === 0) await expect(page.getByTestId('study-next')).toContainText('Nessuna domanda')

  // "Domande su questa parte": lo Studio della prima unità, con le domande da generare.
  await page.goto(`/studio/lezione/${l.id}?unita=${first.id}`)
  await expect(page.getByTestId('study-no-questions')).toContainText(first.id)
  const generated = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith(`/lessons/${l.id}/recall/generate`))
  await page.getByRole('button', { name: 'Genera le domande' }).click()
  expect((await generated).postDataJSON()).toMatchObject({ unit_ids: [first.id] })
  // Generate le domande, la parte parte subito dalle domande (una alla volta).
  await expect(page.getByTestId('study-questions')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/domanda 1 di \d+/)
  expect((await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].questions).toBeGreaterThan(0)

  // Lo Studio della lezione intera: lettura e poi "Mettimi alla prova · N domande" (schermata 06).
  await page.goto(`/studio/lezione/${l.id}`)
  const quiz = page.getByTestId('study-quiz')
  await expect(quiz).toHaveText(/^Mettimi alla prova · \d+ domand[ae]$/)
  const total = Number((await quiz.textContent())!.match(/(\d+) domand/)![1])
  const pending = (await apiGet<Study>(page.request, `/lessons/${l.id}/study`)).units[0].questions
  expect(total).toBe(pending)
  await quiz.click()
  await expect(page.getByTestId('study-questions')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(`domanda 1 di ${total}`)
  await page.getByRole('button', { name: "Rileggi l'unità" }).click()
  await expect(page.getByTestId('study-text')).toBeVisible()
  await page.getByRole('button', { name: 'Torna alle domande' }).click()
  await expect(page.getByTestId('study-question')).toBeVisible()
  for (let i = 0; i < total; i++) {
    await answer(page)
    await page.getByTestId('study-continue').click()
    if (i + 1 < total) await expect(page.getByRole('heading', { level: 1 })).toContainText(`domanda ${i + 2} di ${total}`)
  }
  // Poi l'unità dopo, o la fine dello Studio.
  if (study.units.length > 1) await expect(page.getByRole('heading', { level: 1 })).toContainText(`unità 2 di ${study.units.length}`)
  else await expect(page.getByTestId('study-done')).toContainText('Hai finito lo Studio della lezione.')
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
  const footer = page.getByTestId('study-quiz').or(page.getByTestId('study-next'))
  await expect(footer).toBeInViewport()
  const box = (await footer.boundingBox())!
  expect(box.height).toBeGreaterThanOrEqual(44)
  expect(box.width).toBeGreaterThan(300)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
