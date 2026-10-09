import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, serverState } from './support'

test('pagina lezione: editor protetto, quattro bottoni al passaggio, timer e linguetta fuori vista', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=STUDIO')
  await page.goto(`/lezioni/${lesson.id}`)
  const editor = page.locator('.cm-content').first()
  await editor.click()
  const caret = () => editor.evaluate(el => {
    const selection = window.getSelection()
    return { node: selection?.anchorNode?.textContent, offset: selection?.anchorOffset, inside: el.contains(selection?.anchorNode ?? null) }
  })
  const before = await caret()
  await page.keyboard.press('ArrowRight')
  await expect.poll(caret).not.toEqual(before)
  await expect(page.getByTestId('lesson-jump-buttons-right')).toBeHidden()
  await page.getByTestId('lesson-title-box').click({ position: { x: 100, y: 10 } })
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('lesson-jump-buttons-right')).toBeVisible()
  await expect(page.getByTestId('lesson-jump-buttons-right')).toBeHidden({ timeout: 7000 })
  await page.getByTestId('lesson-jump-zone-left').hover({ position: { x: 72, y: 5 } })
  for (const side of ['left', 'right']) for (const group of ['sameDay', 'sameSubject']) {
    await expect(page.getByTestId(`lesson-jump-${side}-${group}`)).toBeVisible()
    await expect(page.getByTestId(`lesson-jump-${side}-${group}`)).toHaveCSS('opacity', '0.4')
  }
  await page.getByTestId('lesson-jump-left-sameDay').hover()
  // Anche il bottone spento resta raggiungibile per il tooltip col motivo.
  await expect(page.getByRole('tooltip')).toBeVisible()
  await page.mouse.move(500, 500)
  // La fixture è corta: aggiungiamo spazio per provare il titolo fuori vista.
  await page.getByTestId('lesson-title-box').evaluate(el => { document.body.style.minHeight = '2000px'; el.blur(); window.getSelection()?.removeAllRanges(); window.scrollTo(0, 500) })
  await expect(page.getByTestId('lesson-title-box')).not.toBeInViewport()
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByTestId('lesson-jump-tab-left')).toBeVisible()
})

test('iPhone: swipe CDP, linguetta a metà schermo dopo lo scroll', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: serverState().base_url, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  const page = await context.newPage()
  try {
    await loginViaLink(page)
    const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=STUDIO')
    await page.goto(`/lezioni/${lesson.id}`)
    await expect(page.locator('.cm-content').first()).toBeVisible()
    // La fixture è corta e l'editor ne assesta l'altezza dopo il primo frame.
    await page.getByTestId('lesson-page').evaluate(el => { el.style.minHeight = '1800px' })
    await expect.poll(() => page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
      window.getSelection()?.removeAllRanges()
      window.scrollTo(0, 350)
      return window.scrollY
    })).toBeGreaterThan(0)
    const session = await page.context().newCDPSession(page)
    await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 280, y: 400 }] })
    await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 190, y: 401 }] })
    await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 100, y: 401 }] })
    await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    const tab = page.getByTestId('lesson-jump-tab-right')
    await expect(tab).toBeVisible()
    const box = await tab.boundingBox()
    expect(box!.y).toBeGreaterThan(0)
    expect(box!.y + box!.height).toBeLessThan(844)
    expect(Math.abs(box!.y + box!.height / 2 - 422)).toBeLessThan(2)
    await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}$`))
    await session.detach()
  } finally { await context.close() }
})


test('pagina lezione: include le non pronte e conserva il pannello nel cambio', async ({ page }) => {
  await loginViaLink(page)
  const [source] = await apiGet<{ id: number; data: string }[]>(page.request, '/lessons?materia=STUDIO_NAV')
  const [target] = await apiGet<{ id: number; materia: string; data: string; ora: string }[]>(page.request, '/lessons?materia=FISIOLOGIA')
  try {
    expect((await page.request.patch(`/api/v1/lessons/${target.id}/metadata`, { headers: authHeaders(), data: { data: source.data, ora: '23:59' } })).ok()).toBeTruthy()
    await page.goto(`/lezioni/${source.id}?panel=dettagli`)
    await page.getByTestId('lesson-title-box').click({ position: { x: 100, y: 10 } })
    await expect(page.getByTestId('lesson-panel')).toBeVisible()
    const zone = await page.getByTestId('lesson-jump-zone-right').boundingBox()
    const panel = await page.getByTestId('lesson-panel').boundingBox()
    expect(zone!.x + zone!.width).toBeLessThanOrEqual(panel!.x)
    await page.keyboard.press('ArrowRight')
    await page.getByTestId('lesson-jump-right-sameDay').click()
    await expect(page).toHaveURL(new RegExp(`/lezioni/${target.id}\\?panel=dettagli$`))
    await expect(page.getByTestId('lesson-details')).toBeVisible()
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  } finally {
    await page.goto('about:blank')
    expect((await page.request.patch(`/api/v1/lessons/${target.id}/metadata`, { headers: authHeaders(), data: { data: target.data, ora: target.ora } })).ok()).toBeTruthy()
  }
})


test('il player conserva le frecce quando il mouse è sul riquadro audio', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=BIOCHIMICA')
  await page.goto(`/lezioni/${lesson.id}`)
  const player = page.getByTestId('audio-player')
  await expect(player).toBeVisible()
  await expect.poll(() => player.locator('audio').evaluate((audio: HTMLAudioElement) => audio.duration)).toBeGreaterThan(5)
  await player.hover()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => player.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime)).toBeGreaterThan(0)
  await expect(page.getByTestId('lesson-jump-tab-right')).toHaveCount(0)
  await expect(page.getByTestId('lesson-jump-right-sameDay')).not.toBeVisible()
})
