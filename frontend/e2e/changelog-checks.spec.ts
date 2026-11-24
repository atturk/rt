import { expect } from '@playwright/test'
import { test, loginViaLink } from './support'

test('Novità conserva la spunta e la voce barrata dopo il ricaricamento', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/info')
  const toggle = page.getByRole('button', { name: /^4\.2\.4b3/ })
  const version = page.locator('div').filter({ has: toggle }).last()
  // La sezione della versione installata è già aperta: si apre solo se chiusa.
  const open = async () => { if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click() }
  await open()
  const checkbox = version.getByRole('checkbox').first()
  await checkbox.check()
  const text = checkbox.locator('..').locator('span')
  await expect(text).toHaveClass(/line-through/)
  await page.reload()
  await open()
  await expect(checkbox).toBeChecked()
  await expect(text).toHaveClass(/line-through/)
  await checkbox.uncheck()
  await page.reload()
  await open()
  await expect(checkbox).not.toBeChecked()
  await expect(text).not.toHaveClass(/line-through/)
})
