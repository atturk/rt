import { expect, test } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink } from './support'

// RT4-FA6, 4.2.2: sezione Telegram delle Impostazioni. Gira dopo settings.spec.ts (stesso server, in serie), che ha
// salvato token, Chat ID e i topic BIOCHIMICA (12) e ANATOMIA (27) contro la Bot API finta.

type Notification = { kind: string; text: string; topic_id: number | null; ok: boolean }

test('sezione Telegram: chat del gruppo, topic con prova, ultime notifiche, /bot porta qui', async ({ page }) => {
  await loginViaLink(page)
  // Bot, gruppo, topic e notifiche stanno nella sezione Telegram delle Impostazioni (4.2.2).
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await page.getByRole('navigation', { name: 'Sezioni delle impostazioni' }).getByRole('link', { name: 'Telegram' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)
  await expect(page.getByTestId('telegram-bot')).toBeVisible()

  const chat = page.getByTestId('chat_id-value')
  await expect(chat).toHaveText('-100…7890')
  await page.getByRole('button', { name: 'Mostra Chat ID' }).click()
  await expect(chat).toHaveText('-1001234567890')
  await page.getByRole('button', { name: 'Nascondi Chat ID' }).click()
  await expect(chat).toHaveText('-100…7890')

  const rows = page.getByTestId('topic-row')
  const biochimica = rows.filter({ has: page.locator('input[value="BIOCHIMICA"]') })
  await expect(biochimica).toHaveCount(1)
  await expect(biochimica.getByLabel(/^Topic \d+$/)).toHaveValue('12')
  await biochimica.getByRole('button', { name: /^Prova topic \d+$/ }).click()
  await expect(biochimica.getByTestId('topic-test-result')).toHaveText('Messaggio inviato nel topic 12.')

  // Le prove compaiono tra le ultime notifiche, anche dopo la ricarica; /bot porta qui.
  const notifications = page.getByRole('region', { name: 'Ultime notifiche inviate' }).getByTestId('bot-notification')
  await expect(notifications.first()).toContainText('Questo è il topic di BIOCHIMICA')
  await page.goto('/bot')
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)
  await expect(notifications.first()).toContainText('Questo è il topic di BIOCHIMICA')
  await expect(notifications.first()).toContainText('topic 12')
  const sent = await apiGet<Notification[]>(page.request, '/telegram/notifications')
  expect(sent[0]).toMatchObject({ kind: 'prova', text: 'Questo è il topic di BIOCHIMICA', topic_id: 12, ok: true })
})

test('Telegram spento: la sezione Telegram mostra solo l\'interruttore e il recall si fa solo qui', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number; phases: Record<string, string> }[]>(page.request, '/lessons?materia=BIOCHIMICA')
  await page.goto('/impostazioni/telegram')
  const toggle = page.getByTestId('telegram-enabled').getByLabel('Usa Telegram')
  await expect(toggle).toBeChecked()
  try {
    await toggle.click()
    await expect(toggle).not.toBeChecked()
    await expect(page.getByText('Topic per materia')).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId('telegram-enabled').getByLabel('Usa Telegram')).not.toBeChecked()
    await page.goto(`/lezioni/${lesson.id}/sessione`)
    await expect(page.getByRole('group', { name: 'Tipo di domanda' })).toBeVisible()
    await expect(page.getByText('Telegram')).toHaveCount(0)
  } finally {
    // gli altri test (stesso server) lo vogliono acceso
    await page.request.put('/api/v1/settings/telegram/enabled', { data: { enabled: true }, headers: authHeaders() })
  }
})

