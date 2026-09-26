import { expect, test } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// RT4-FA6: pagina Bot Telegram. Gira dopo settings.spec.ts (stesso server, in serie), che ha
// salvato token, Chat ID e i topic BIOCHIMICA (12) e ANATOMIA (27) contro la Bot API finta.

type Notification = { kind: string; text: string; topic_id: number | null; ok: boolean }

test('pagina Bot Telegram: gruppo, topic con prova, ultime notifiche, link alle impostazioni', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Bot Telegram' }).click()
  await expect(page).toHaveURL(/\/bot$/)
  await expect(page.getByTestId('telegram-bot')).toBeVisible()

  const group = page.getByRole('region', { name: 'Gruppo' })
  await expect(group.getByTestId('chat_id-value')).toHaveText('-100…7890')
  await group.getByRole('button', { name: 'Mostra Chat ID' }).click()
  await expect(group.getByTestId('chat_id-value')).toHaveText('-1001234567890')
  await group.getByRole('button', { name: 'Nascondi Chat ID' }).click()
  await expect(group.getByTestId('chat_id-value')).toHaveText('-100…7890')

  const topics = page.getByRole('region', { name: 'Topic per materia' }).getByTestId('bot-topic')
  await expect(topics).toHaveCount(2)
  await expect(topics.nth(0)).toContainText('ANATOMIA')
  await expect(topics.nth(0)).toContainText('Topic 27 · «Anatomia umana»')
  await expect(topics.nth(1)).toContainText('Topic 12 · «Biochimica»')
  await topics.nth(1).getByRole('button', { name: 'Prova BIOCHIMICA' }).click()
  await expect(topics.nth(1).getByTestId('topic-test-result')).toHaveText('Messaggio inviato nel topic 12.')

  // Le prove compaiono tra le ultime notifiche, anche dopo la ricarica.
  const notifications = page.getByRole('region', { name: 'Ultime notifiche inviate' }).getByTestId('bot-notification')
  await expect(notifications.first()).toContainText('Questo è il topic di BIOCHIMICA')
  await page.reload()
  await expect(notifications.first()).toContainText('Questo è il topic di BIOCHIMICA')
  await expect(notifications.first()).toContainText('topic 12')
  const sent = await apiGet<Notification[]>(page.request, '/telegram/notifications')
  expect(sent[0]).toMatchObject({ kind: 'prova', text: 'Questo è il topic di BIOCHIMICA', topic_id: 12, ok: true })

  await page.getByRole('link', { name: 'Impostazioni Telegram' }).click()
  await expect(page).toHaveURL(/\/impostazioni#telegram$/)
  await expect(page.getByRole('region', { name: 'Telegram', exact: true })).toBeInViewport()
})
