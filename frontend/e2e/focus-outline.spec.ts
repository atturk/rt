import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; materia: string; phases: Record<string, string> }
type Overview = { questions: Record<string, Record<string, number>> }

test('campi di testo senza bordo nero di focus ed outline presente sui pulsanti con focus da tastiera (4.3.3b3 piano 4)', async ({ page }) => {
  test.setTimeout(90_000)
  await loginViaLink(page)

  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const lesson = lessons.find((l) => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')!

  // 1. Assicuriamoci che ci sia almeno una domanda mirata per avere il campo "Risposta scritta"
  const overview = await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)
  if (!(overview.questions.mirata?.pending ?? 0)) {
    const res = await page.request.post(`/api/v1/lessons/${lesson.id}/recall/generate`, {
      headers: authHeaders(),
      data: { qtype: 'mirata', mock: true },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
    await expect.poll(
      async () => (await apiGet<Overview>(page.request, `/lessons/${lesson.id}/recall`)).questions.mirata?.pending ?? 0,
      { timeout: 30_000 },
    ).toBeGreaterThan(0)
  }

  // 2. Apri la sessione di ripasso e passa a Mirata
  await page.goto(`/lezioni/${lesson.id}/sessione`)
  const types = page.getByRole('group', { name: 'Tipo di domanda' })
  await types.getByRole('button', { name: 'Mirata', exact: true }).click()

  const writtenAnswer = page.getByLabel('Risposta scritta')
  await expect(writtenAnswer).toBeVisible()
  await writtenAnswer.focus()
  const writtenOutline = await writtenAnswer.evaluate((el) => getComputedStyle(el).outlineStyle)
  expect(writtenOutline).toBe('none')

  // 3. Studio: apre la chat e verifica che il campo di scrittura non abbia outline
  await page.goto(`/studio/lezione/${lesson.id}`)
  const text = page.getByTestId('study-text')
  await expect(text).toHaveText(/\S.{20,}/)

  await page.keyboard.press('c')
  const panel = page.getByTestId('study-chat-panel')
  await expect(panel).toBeVisible()
  const askInput = page.getByTestId('study-chat-input')
  await expect(askInput).toBeVisible()
  await askInput.focus()
  const askOutline = await askInput.evaluate((el) => getComputedStyle(el).outlineStyle)
  expect(askOutline).toBe('none')

  // 4. Focus da tastiera su un pulsante: outline presente
  // Tab sposta il focus sui controlli interattivi (pulsanti/link)
  await page.keyboard.press('Tab')
  const focusedTag = await page.evaluate(() => document.activeElement?.tagName.toLowerCase())
  const focusedOutline = await page.evaluate(() => {
    const el = document.activeElement
    return el ? getComputedStyle(el).outlineStyle : ''
  })
  expect(['button', 'a']).toContain(focusedTag)
  expect(focusedOutline).not.toBe('none')
})
