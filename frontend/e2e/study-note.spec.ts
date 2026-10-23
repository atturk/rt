import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

type Lesson = { id: number; materia: string; data: string }

async function getLesson(page: any, materia: string): Promise<Lesson> {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

test('Verifica e Chiedi nello Studio: selezione, risposta in mock, Applica e sincronizzazione con editor', async ({ page }) => {
  test.setTimeout(90_000)
  await loginViaLink(page)

  const l = await getLesson(page, 'FARMACOLOGIA')
  await page.goto(`/studio/lezione/${l.id}`)

  const text = page.getByTestId('study-text')
  await expect(text).toHaveText(/\S.{20,}/)

  // 1. Attiva lo strumento Verifica (tasto V)
  await page.keyboard.press('v')
  await expect(text).toHaveAttribute('data-hl-mode', 'verifica')

  // 2. Seleziona un passaggio di testo come col mouse
  const selected = await text.evaluate((root) => {
    const node = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      { acceptNode: (n) => ((n.textContent ?? '').trim().length > 15 ? 1 : 3) },
    ).nextNode()!
    const range = document.createRange()
    const start = node.textContent!.search(/\S/)
    range.setStart(node, start)
    range.setEnd(node, start + 12)
    getSelection()!.removeAllRanges()
    getSelection()!.addRange(range)
    const chosen = range.toString()
    root.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    return chosen
  })

  // 3. Popup si apre con il testo selezionato
  const popup = page.getByTestId('study-note-popup')
  await expect(popup).toBeVisible()
  await expect(page.getByTestId('study-note-quote')).toHaveText(selected)

  // 4. Inserisce richiesta con parola chiave 'errato' per risposta mock con correzione
  await page.getByTestId('study-note-input').fill('Verifica se questo passaggio è errato')
  await page.getByTestId('study-note-submit').click()

  // 5. Attende il completamento del job in mock
  await expect(page.getByTestId('study-note-verdict')).toBeVisible({ timeout: 45_000 })
  await expect(page.getByTestId('study-note-verdict')).toHaveText('Errato')

  const applyBtn = page.getByTestId('study-note-apply')
  await expect(applyBtn).toBeVisible()

  // 6. Clicca Applica
  await applyBtn.click()
  await expect(popup.getByText('Correzione applicata')).toBeVisible()

  // 7. Il testo nello Studio è aggiornato con la correzione
  await expect(text).toContainText(selected)
  await expect(text).toContainText('corretto')

  // Chiude il popup
  await page.getByLabel('Chiudi').click()
  await expect(popup).not.toBeVisible()

  // 8. Va alla pagina della lezione (editor)
  await page.goto(`/lezioni/${l.id}`)
  const editor = page.getByTestId('lesson-document')
  await expect(editor).toBeVisible()

  // 9. Il testo corretto è presente nell'editor
  await expect(editor).toContainText(selected)
  await expect(editor).toContainText('corretto')

  // Le note non segnano il testo finché il pannello non è aperto (SN1).
  await expect(editor.locator('[data-study-note]')).toHaveCount(0)
  await page.goto(`/lezioni/${l.id}?panel=note`)
  // 10. La sottolineatura della nota è presente solo col pannello aperto
  const noteMark = editor.locator('[data-study-note]').first()
  await expect(noteMark).toBeVisible()

  // 11. Clic sulla sottolineatura apre il pannello 'note' con la voce
  await noteMark.click()
  const panel = page.getByTestId('lesson-panel')
  await expect(panel).toBeVisible()
  await expect(panel).toHaveAttribute('data-view', 'note')
  await expect(page.getByTestId('study-notes-detail')).toBeVisible()
  await expect(page.getByTestId('detail-quote')).toHaveText(selected)
})

test('Chiedi a 390 px: invio visibile e cliccabile sopra la barra delle sezioni', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginViaLink(page)
  const l = await getLesson(page, 'BIOCHIMICA')
  await page.goto(`/studio/lezione/${l.id}`)
  const text = page.getByTestId('study-text')
  await expect(text).toHaveText(/\S.{20,}/)
  const openTools = async () => {
    const toggle = page.getByTestId('study-tools-toggle')
    if (await toggle.isVisible().catch(() => false)) {
      await toggle.hover()
      await expect(page.getByTestId('highlight-tools')).toBeVisible()
    }
  }
  await openTools()
  await page.getByTestId('highlight-chiedi').click()
  await text.evaluate((root) => {
    const node = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => (node.textContent ?? '').trim().length > 20 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    }).nextNode()!
    const range = document.createRange()
    range.setStart(node, 0)
    range.setEnd(node, 20)
    getSelection()!.removeAllRanges()
    getSelection()!.addRange(range)
    root.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  const popup = page.getByTestId('study-note-popup')
  await expect(popup).toHaveAttribute('data-sheet-level', '1')
  await page.getByTestId('study-note-input').fill('Spiega questo passaggio')
  const send = page.getByTestId('study-note-submit')
  await expect(send).toBeInViewport()
  expect(await send.evaluate((button) => {
    const rect = button.getBoundingClientRect()
    return button.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2))
  })).toBe(true)
  await send.click()
  await expect(page.getByTestId('study-note-answer')).toBeVisible({ timeout: 45_000 })
})

test('formule nello Studio: selezione in LaTeX, copia, evidenziatore e citazione Chiedi', async ({ page, context }) => {
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
    await openTools()
    await page.getByTestId('highlight-chiedi').click()
    await selectFormula()
    await root.dispatchEvent('mouseup', { button: 0 })
    const quote = page.getByTestId('study-note-quote')
    await expect(quote).toContainText('Formula')
    await expect(quote.locator('math')).toHaveAttribute('data-rt-source', '$z$')
  } finally {
    const rows = await apiGet<{ id: number }[]>(page.request, `/lessons/${l.id}/highlights?unit=1.1`)
    for (const row of rows.filter(row => !previous.some(old => old.id === row.id))) {
      expect((await page.request.delete(`/api/v1/lessons/${l.id}/highlights/${row.id}`, { headers: authHeaders() })).ok()).toBe(true)
    }
  }
})
