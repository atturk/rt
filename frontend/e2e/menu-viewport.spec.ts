import { expect, type Locator, type Page } from '@playwright/test'
import { test, apiGet, loginViaLink } from './support'

async function insideScreen(page: Page, menu: Locator) {
  await expect(menu).toBeVisible()
  const viewport = page.viewportSize()!
  await expect.poll(async () => {
    const box = await menu.boundingBox()
    return !!box && box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height
  }).toBe(true)
}

for (const width of [1280, 390]) {
  test(`menu Verifica ed Esporta interamente visibili a ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await loginViaLink(page)
    const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
    await page.goto(`/lezioni/${lesson.id}?panel=verifica`)
    const panel = page.getByTestId('lesson-review-panel')
    await panel.getByRole('button', { name: 'Azioni della verifica' }).click()
    await insideScreen(page, page.getByRole('menu', { name: 'Azioni della verifica' }))
    await expect(page.getByRole('menu', { name: 'Azioni della verifica' }).getByRole('menuitem').first()).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(panel).toBeVisible()
    const unitMenu = panel.getByRole('button', { name: /^Azioni sull/ }).first()
    await unitMenu.click()
    await insideScreen(page, page.getByRole('menu', { name: /^Azioni sull/ }))
    await page.keyboard.press('Escape')
    await page.goto(`/lezioni/${lesson.id}`)
    await page.getByTestId('lesson-actions').getByRole('button', { name: 'Esporta' }).click()
    await insideScreen(page, page.getByRole('menu', { name: 'Esporta' }))
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('lesson-actions').getByRole('button', { name: 'Esporta' })).toBeFocused()
  })
}
