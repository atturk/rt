import { expect } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink } from './support'

// Sezione Telegram delle Impostazioni: notifiche nella chat personale. Gira dopo settings.spec.ts
// (stesso server, in serie), che ha salvato il token e collegato la chat contro la Bot API finta.

type Notification = { kind: string; text: string; ok: boolean }

test('Telegram: messaggio di prova, ultime notifiche, /bot porta qui', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await page.getByRole('navigation', { name: 'Sezioni delle impostazioni' }).getByRole('link', { name: 'Telegram' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)

  const chat = page.getByTestId('chat_id-value')
  await expect(chat).toHaveText('55…23')
  await page.getByRole('button', { name: 'Mostra Chat ID' }).click()
  await expect(chat).toHaveText('555123')
  await page.getByRole('button', { name: 'Nascondi Chat ID' }).click()

  await page.getByRole('button', { name: 'Manda un messaggio di prova' }).click()
  await expect(page.getByTestId('telegram-test-result')).toHaveText('Messaggio di prova inviato: controlla Telegram.')

  // La prova compare tra le ultime notifiche, anche dopo la ricarica; /bot porta qui.
  const notifications = page.getByRole('region', { name: 'Ultime notifiche inviate' }).getByTestId('bot-notification')
  await expect(notifications.first()).toContainText('Da ora le notifiche di RT arrivano in questa chat')
  await page.goto('/bot')
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)
  await expect(notifications.first()).toContainText('Prova')
  const sent = await apiGet<Notification[]>(page.request, '/telegram/notifications')
  expect(sent[0]).toMatchObject({ kind: 'prova', ok: true })
})

test('Telegram spento: resta solo l\'interruttore', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/telegram')
  const toggle = page.getByTestId('telegram-enabled').getByLabel('Ricevi le notifiche su Telegram')
  await expect(toggle).toBeChecked()
  try {
    await toggle.click()
    await expect(toggle).not.toBeChecked()
    await expect(page.getByRole('button', { name: 'Collega la chat' })).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId('telegram-enabled').getByLabel('Ricevi le notifiche su Telegram')).not.toBeChecked()
  } finally {
    // gli altri test (stesso server) lo vogliono acceso
    await page.request.put('/api/v1/settings/telegram/enabled', { data: { enabled: true }, headers: authHeaders() })
  }
})
