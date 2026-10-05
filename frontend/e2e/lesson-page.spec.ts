import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// Pagina della lezione del design 4.2 (schermate 02 e 02b): barra audio con la velocità a valori
// fissi e menu contestuale del documento (Copia, Leggi da qui, Genera, Domande, Verifica).

type Lesson = { id: number; materia: string }
type Enrichment = { elements: { id: string; kind: string; request?: string; selection?: string; context_unit_ids?: string[] }[] }

async function lessonId(page: Page, materia: string) {
  const [lesson] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return lesson.id
}

test('barra audio: play e velocità 1× → 1,25× → 1,5× → 1,75× → 2× → 1×, ricordata dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)
  const player = page.getByTestId('audio-player')
  await expect(player).toBeVisible()
  // Fissa in basso, anche dopo lo scorrimento del documento.
  expect(await player.evaluate((el) => getComputedStyle(el).position)).toBe('fixed')
  await expect(player.getByRole('button', { name: 'Riproduci' })).toBeVisible()
  await expect(player.getByRole('slider', { name: "Posizione nell'audio" })).toBeVisible()

  const speed = player.getByTestId('speed-button')
  await expect(speed).toHaveText('1×')
  await speed.hover()
  await expect(page.getByRole('tooltip')).toHaveText('Velocità: 1× · 1,25× · 1,5× · 1,75× · 2×')
  for (const [label, rate] of [['1,25×', 1.25], ['1,5×', 1.5], ['1,75×', 1.75], ['2×', 2], ['1×', 1]] as const) {
    await speed.click()
    await expect(speed).toHaveText(label)
    await expect(speed).toHaveAccessibleName(`Velocità di riproduzione: ${label}`)
    await expect.poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.playbackRate)).toBeCloseTo(rate)
  }
  await speed.click()
  await expect(speed).toHaveText('1,25×')
  await page.reload()
  await expect(speed).toHaveText('1,25×')
  await expect.poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.playbackRate)).toBeCloseTo(1.25)

  // Play e pausa con l'audio muto.
  await page.locator('audio').evaluate((a: HTMLAudioElement) => (a.muted = true))
  await player.getByRole('button', { name: 'Riproduci' }).click()
  await expect(player.getByRole('button', { name: 'Pausa' })).toBeVisible()
  await player.getByRole('button', { name: 'Pausa' }).click()
  await expect(player.getByRole('button', { name: 'Riproduci' })).toBeVisible()
})

test('menu contestuale: Copia, Leggi da qui in arrivo, Genera col regista e Verifica questa parte', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await loginViaLink(page)
  const id = await lessonId(page, 'CHIRURGIA')
  await page.goto(`/lezioni/${id}`)
  const doc = page.getByTestId('lesson-document')
  const heading = doc.locator('[data-unit-id]').first()
  const unit = (await heading.getAttribute('data-unit-id'))!

  // Il clic destro su un testo senza selezione lascia il menu del browser.
  const paragraph = doc.locator('.cm-line:not([data-unit-id]):not(.cm-atomic-h2):not(.cm-atomic-h3)', { hasText: /\w+ \w+ \w+/ }).first()
  await paragraph.click({ button: 'right' })
  await expect(page.getByTestId('document-menu')).toHaveCount(0)

  // Clic destro sul titolo di una subunità: la parte è quella subunità.
  await heading.click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Azioni sul testo' })
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('menuitem')).toHaveText(['Copia', 'Leggi da qui', 'Genera', 'Domande su questa parte', 'Verifica questa parte'])
  await expect(page.getByTestId('document-menu-part')).toHaveText(`Questa parte: ${unit}`)
  await expect(menu.getByRole('menuitem', { name: 'Copia' })).toBeFocused()
  const later = menu.getByRole('menuitem', { name: 'Leggi da qui' })
  await expect(later).toHaveAttribute('aria-disabled', 'true')
  await later.hover()
  await expect(page.getByRole('tooltip')).toContainText('In arrivo')
  // Le frecce scorrono le voci; Esc chiude.
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: 'Genera' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)

  // Copia: il testo selezionato negli appunti.
  // Nell'editor: la prima riga di testo dell'unità (dopo titolo e timecode).
  const selected = paragraph
  const text = await selected.evaluate((p) => {
    const range = document.createRange()
    range.selectNodeContents(p)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    return sel.toString()
  })
  await selected.click({ button: 'right' })
  await expect(menu).toBeVisible()
  await expect(page.getByTestId('document-menu-part')).toHaveText(`Questa parte: ${unit}`)
  await menu.getByRole('menuitem', { name: 'Copia' }).click()
  await expect(menu).toHaveCount(0)
  // Si copia il Markdown (come in Obsidian): senza i segni è il testo che si vede.
  const plain = (markdown: string) => markdown.replace(/[[\]*_`]/g, '')
  await expect.poll(async () => plain(await page.evaluate(() => navigator.clipboard.readText()))).toBe(text)

  // Genera (schermata 02b): tipo, richiesta, invio al regista; l'elemento parte in Arricchimento.
  await selected.evaluate((p) => {
    const range = document.createRange()
    range.selectNodeContents(p)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
  })
  await selected.click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Genera' }).click()
  const popover = page.getByTestId('generate-popover')
  await expect(popover).toBeVisible()
  await expect(popover.getByRole('textbox')).toBeFocused()
  await expect(popover.getByRole('textbox')).toHaveAttribute('placeholder', 'Che tipo di elemento grafico vuoi vedere?')
  await expect(popover.getByRole('button', { name: 'Genera' })).toHaveAttribute('aria-disabled', 'true')
  await popover.getByRole('button', { name: 'Infografica' }).click()
  await expect(popover.getByRole('textbox')).toHaveAttribute('placeholder', 'Quale infografica vuoi vedere?')
  await popover.getByRole('textbox').fill('Le fasi della sutura in quattro riquadri')
  const posted = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/lessons/${id}/enrichment/generate`))
  await popover.getByRole('button', { name: 'Genera' }).click()
  expect((await posted).status()).toBe(202)
  const body = (await posted).request().postDataJSON() as { kind: string; request: string; selection: string; unit_ids: string[] }
  expect(body).toMatchObject({ kind: 'infographic', request: 'Le fasi della sutura in quattro riquadri', unit_ids: [unit] })
  expect(plain(body.selection)).toBe(text)
  await expect(popover).toHaveCount(0)
  await expect(page.getByTestId('generate-queued')).toContainText(`Richiesta inviata per ${unit}`)
  const enrichment = await apiGet<Enrichment>(page.request, `/lessons/${id}/enrichment`)
  const element = enrichment.elements.find((e) => e.request === 'Le fasi della sutura in quattro riquadri')
  expect(element?.kind).toBe('infographic')
  expect(element?.context_unit_ids).toEqual([unit])

  // Verifica questa parte: review_unit con il contesto dell'unità madre, avanzamento dal vivo.
  // L'elemento generato arriva mentre si clicca e sposta il documento: si riapre il menu finché non c'è.
  const verifica = menu.getByRole('menuitem', { name: 'Verifica questa parte' })
  await expect(async () => {
    await heading.click({ button: 'right' })
    await expect(verifica).toBeVisible({ timeout: 2000 })
  }).toPass({ timeout: 30_000 })
  const review = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith(`/lessons/${id}/jobs`))
  await verifica.click()
  expect((await review).postDataJSON()).toMatchObject({ type: 'run_phase', phase: 'review', units: [unit], parent_context: true })
  const status = page.getByTestId('part-review')
  await expect(status).toBeVisible()
  await expect(status).toHaveAttribute('data-state', 'succeeded', { timeout: 45_000 })
  await expect(status.getByRole('link', { name: 'Apri la verifica' })).toHaveAttribute('href', `/lezioni/${id}?panel=verifica`)
})

test('menu contestuale: Domande su questa parte apre il pannello Domande sulle unità della selezione', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'BIOCHIMICA')
  await page.goto(`/lezioni/${id}`)
  const heading = page.getByTestId('lesson-document').locator('[data-unit-id]').first()
  const unit = (await heading.getAttribute('data-unit-id'))!
  await heading.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Domande su questa parte' }).click()
  const panel = page.locator('[data-testid=lesson-panel][data-view=domande]')
  await expect(panel).toBeVisible()
  await expect(panel).toHaveAttribute('aria-label', `Domande unità ${unit}`)
  await expect(panel.getByText(`Nuove domande su ${unit}`)).toBeVisible()
})

// Come l'allineamento in settings.spec.ts si scrive su CHIRURGIA: la lezione di BIOCHIMICA la
// esporta e reimporta new-lesson.spec.ts, che vuole il documento come l'ha scritto la pipeline.
test('formule: il LaTeX si vede reso nell’editor e torna in chiaro con il cursore dentro', async ({ page }) => {
  await loginViaLink(page)
  const id = await lessonId(page, 'CHIRURGIA')
  const original = await apiGet<{ markdown: string }>(page.request, `/lessons/${id}/document`)
  const markdown = `${original.markdown.trimEnd()}\n\nIn riga $E = mc^2$ e da sola:\n\n$$\\int_0^1 x\\,dx = \\frac{1}{2}$$\n`
  const lease = await page.request.post(`/api/v1/lessons/${id}/document/lease`, { headers: authHeaders() })
  expect(lease.ok()).toBeTruthy()
  const { token } = await lease.json()
  const save = await page.request.put(`/api/v1/lessons/${id}/document/draft`, { headers: authHeaders(), data: { markdown, lease_token: token } })
  expect(save.ok(), await save.text()).toBeTruthy()
  await page.request.delete(`/api/v1/lessons/${id}/document/lease?token=${encodeURIComponent(token)}`, { headers: authHeaders() })

  await page.goto(`/lezioni/${id}`)
  const editor = page.getByTestId('lesson-document')
  const formulas = editor.locator('.rt-editor-math')
  await expect(formulas).toHaveCount(2)
  await expect(formulas.first().locator('math')).toBeVisible()
  await expect(editor).not.toContainText('$E = mc^2$')
  // Il clic sulla formula porta il cursore dentro: tornano i delimitatori, come in Obsidian.
  await formulas.first().click()
  await expect(editor).toContainText('$E = mc^2$')
})
