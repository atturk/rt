import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; materia: string; data: string }

async function getLesson(page: any, materia: string): Promise<Lesson> {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

test('chat dello Studio: tasto C, risposta in mock, salvataggio in Verifiche e domande, cancellazione', async ({ page }) => {
  test.setTimeout(90_000)
  await loginViaLink(page)
  const l = await getLesson(page, 'FARMACOLOGIA')
  await page.goto(`/studio/lezione/${l.id}`)
  const text = page.getByTestId('study-text')
  await expect(text).toHaveText(/\S.{20,}/)

  await page.keyboard.press('c')
  const panel = page.getByTestId('study-chat-panel')
  await expect(panel).toBeVisible()
  const input = page.getByTestId('study-chat-input')
  await input.fill('Spiega questo passaggio')
  // Mentre si scrive, le scorciatoie dello Studio sono disattivate: "c" non chiude la chat.
  await input.press('c')
  await expect(panel).toBeVisible()
  await page.getByTestId('study-chat-send').click()

  const answer = panel.locator('[data-testid^="chat-msg-assistant-"]').first()
  await expect(answer).toBeVisible({ timeout: 45_000 })
  const id = (await answer.getAttribute('data-testid'))!.replace('chat-msg-assistant-', '')
  await page.getByTestId(`chat-save-note-${id}`).click()
  await expect(page.getByTestId(`chat-save-note-${id}`)).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(async () => (await apiGet<unknown[]>(page.request, `/lessons/${l.id}/study-notes`)).length).toBeGreaterThan(0)

  // La cronologia resta dopo il ricaricamento.
  await page.reload()
  await expect(text).toHaveText(/\S.{20,}/)
  await page.getByTestId('study-chat-btn').click()
  await expect(page.getByTestId(`chat-msg-assistant-${id}`)).toBeVisible()

  // Il cestino svuota la chat, la nota resta.
  await page.getByTestId('study-chat-clear').click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancella', exact: true }).click()
  await expect(page.getByTestId('study-chat-empty')).toBeVisible()
  expect((await apiGet<unknown[]>(page.request, `/lessons/${l.id}/study-notes`)).length).toBeGreaterThan(0)
  await page.getByTestId('study-chat-close').click()
  await expect(panel).not.toBeVisible()
})

test('chat a 390 px: a schermo intero, invio visibile e cliccabile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginViaLink(page)
  const l = await getLesson(page, 'BIOCHIMICA')
  await page.goto(`/studio/lezione/${l.id}`)
  await expect(page.getByTestId('study-text')).toHaveText(/\S.{20,}/)
  const toggle = page.getByTestId('study-tools-toggle')
  if (await toggle.isVisible().catch(() => false)) {
    await toggle.click()
    await expect(page.getByTestId('highlight-tools')).toBeVisible()
  }
  await page.getByTestId('study-chat-btn').click()
  const panel = page.getByTestId('study-chat-panel')
  await expect(panel).toBeVisible()
  const box = (await panel.boundingBox())!
  expect(box.width).toBeGreaterThanOrEqual(389)
  await page.getByTestId('study-chat-input').fill('Spiega questo passaggio')
  const send = page.getByTestId('study-chat-send')
  await expect(send).toBeInViewport()
  expect(await send.evaluate((button) => {
    const rect = button.getBoundingClientRect()
    return button.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2))
  })).toBe(true)
  await send.click()
  await expect(panel.locator('[data-testid^="chat-msg-assistant-"]').first()).toBeVisible({ timeout: 45_000 })
  await page.getByTestId('study-chat-clear').click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancella', exact: true }).click()
  await expect(page.getByTestId('study-chat-empty')).toBeVisible()
})

test('formule nello Studio: selezione in LaTeX, copia ed evidenziatore', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await loginViaLink(page)
  const l = await getLesson(page, 'STUDIO')
  const previous = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=1.1`)
  try {
    const openTools = async () => {
      const toggle = page.getByTestId('study-tools-toggle')
      if (await toggle.isVisible().catch(() => false)) {
        await toggle.hover()
        await expect(page.getByTestId('highlight-tools')).toBeVisible()
      }
    }
    await page.goto(`/studio/lezione/${l.id}`)
    await expect(page.getByTestId('study-dots')).toBeVisible()
    await page.getByTestId('study-dots').locator('button').first().click()
    const root = page.getByTestId('study-text')
    const math = root.locator('math').first()
    await expect(math).toHaveAttribute('data-rt-source', '$z$')
    // La copia deve funzionare anche senza uno strumento attivo.
    await openTools()
    if (await page.getByTestId('highlight-pen').getAttribute('aria-pressed') === 'true') await page.getByTestId('highlight-pen').click()
    const selectFormula = () => root.evaluate(root => {
      const p = root.querySelector('math')!.parentElement!
      const range = document.createRange()
      range.setStart(p.firstChild!, 0)
      range.setEndAfter(root.querySelector('.rt-math-src')!)
      getSelection()!.removeAllRanges(); getSelection()!.addRange(range)
    })
    await selectFormula()
    await expect(math).toHaveClass(/rt-math-raw/)
    await expect(root.locator('.rt-math-src').first()).toBeVisible()
    await expect(root.locator('.rt-math-src').first()).toHaveText('$z$')
    await page.keyboard.press('ControlOrMeta+c')
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('Formula $z$')
    await page.evaluate(() => getSelection()!.removeAllRanges())
    await expect(math).not.toHaveClass(/rt-math-raw/)
    await expect(math).toBeVisible()

    await openTools()
    await page.getByTestId('highlight-pen').click()
    await selectFormula()
    await root.dispatchEvent('mouseup', { button: 0 })
    await expect(math).toHaveClass(/rt-hl-math/)
    await expect(math.locator('.rt-hl')).toHaveCount(0)
    await expect.poll(async () => (await apiGet<{ source: { text?: string } }[]>(page.request, `/lessons/${l.id}/highlights?unit=1.1`)).some(row => row.source.text === 'Formula $z$')).toBe(true)
  } finally {
    const rows = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=1.1`)
    for (const row of rows.filter(row => !previous.some(old => old.id === row.id))) {
      expect((await page.request.delete(`/api/v1/lessons/${l.id}/highlights/${row.id}`, { headers: authHeaders() })).ok()).toBe(true)
    }
  }
})
