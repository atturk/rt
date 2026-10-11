import { expect } from '@playwright/test'
import { test, loginViaLink } from './support'

test('Novità conserva la spunta e la voce barrata dopo il ricaricamento', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/info')
  const version = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: /^4\.2\.4b3/ }) })
  await version.locator('summary').click()
  const checkbox = version.getByRole('checkbox').first()
  await checkbox.check()
  const text = checkbox.locator('..').locator('span')
  await expect(text).toHaveClass(/line-through/)
  await page.reload()
  await version.locator('summary').click()
  await expect(checkbox).toBeChecked()
  await expect(text).toHaveClass(/line-through/)
  await checkbox.uncheck()
  await page.reload()
  await version.locator('summary').click()
  await expect(checkbox).not.toBeChecked()
  await expect(text).not.toHaveClass(/line-through/)
})
