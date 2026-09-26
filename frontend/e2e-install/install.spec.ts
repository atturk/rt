import { expect, test } from '@playwright/test'

// RT4-G2: dopo il comando di installazione su un Mac pulito la web app risponde (servizio
// launchd dell'API) e il link monouso di 'rt web --no-browser' apre la configurazione guidata.
// Il job CI 'installer' passa il link in RT_LOGIN_URL.
test('la web app installata apre la configurazione guidata', async ({ page }) => {
  const link = process.env.RT_LOGIN_URL
  expect(link, 'RT_LOGIN_URL mancante').toBeTruthy()
  await page.goto(link!)
  await expect(page).not.toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: 'Configurazione guidata' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Configurazione guidata' })).toBeVisible()
})
