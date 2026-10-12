import { expect } from '@playwright/test'
import { test, authHeaders, loginViaLink } from './support'

test('calendario: navigazione, settimana tipo, popup evento e riepilogo', async ({ page }) => {
  await loginViaLink(page)

  // 1. Aggiunge uno slot di prova nella settimana tipo (lunedì 09:30 - 11:30)
  const addRes = await page.request.post('/api/v1/calendar/template', {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    data: JSON.stringify({
      day_of_week: 0,
      start_time: '09:30',
      end_time: '11:30',
      materia: 'Data Mining',
      docente: 'Prof. Ferraris',
    }),
  })
  expect(addRes.ok()).toBeTruthy()
  const createdTpl = (await addRes.json()) as { id: number }

  try {
    // 2. Naviga alla pagina Calendario tramite la barra laterale
    const nav = page.getByRole('navigation', { name: 'Navigazione' })
    const calendarLink = nav.getByRole('link', { name: 'Calendario' })
    await calendarLink.click()
    await expect(page).toHaveURL(/\/calendario/)

    // Intestazione
    await expect(page.getByRole('heading', { level: 1, name: 'Calendario' })).toBeVisible()
    const weekLabel = page.getByTestId('calendar-week-label')
    await expect(weekLabel).toBeVisible()

    // Navigazione settimane
    const initialText = await weekLabel.innerText()
    await page.getByRole('button', { name: 'Settimana successiva' }).click()
    await expect(weekLabel).not.toHaveText(initialText)
    await page.getByRole('button', { name: 'Oggi' }).click()
    await expect(weekLabel).toHaveText(initialText)

    // 3. Verifica presenza dello slot nella griglia
    const slot = page.getByTestId('calendar-event-tpl_' + createdTpl.id).first()
    await expect(slot).toBeVisible()
    await expect(slot).toContainText('Data Mining', { ignoreCase: true })
    await expect(slot).toContainText('09:30')

    // 4. Clic sullo slot apre il popup dell'evento
    await slot.click()
    const eventPopup = page.getByTestId('calendar-event-popup')
    await expect(eventPopup).toBeVisible()
    await expect(eventPopup).toContainText('Data Mining', { ignoreCase: true })
    await expect(eventPopup).toContainText('09:30–11:30')

    // Cambia stato a "Da saltare"
    await eventPopup.getByRole('button', { name: 'Da saltare' }).click()
    // Chiude il popup premendo Escape
    await page.keyboard.press('Escape')
    await expect(eventPopup).toHaveCount(0)

    // 5. Riepilogo settimana (ⓘ)
    const infoButton = page.getByRole('button', { name: 'Riepilogo della settimana' })
    await infoButton.click()
    const weekPopup = page.getByTestId('calendar-week-popup')
    await expect(weekPopup).toBeVisible()
    await expect(weekPopup).toContainText('Settimana')
    await page.keyboard.press('Escape')
    await expect(weekPopup).toHaveCount(0)

    // 6. Menu del giorno (tre puntini / clic su testata lunedì)
    const dayMenuBtn = page.getByTestId('calendar-day-header-Lun')
    await dayMenuBtn.click()
    const dayMenu = page.getByTestId('calendar-day-menu')
    await expect(dayMenu).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dayMenu).toHaveCount(0)
  } finally {
    // Pulizia slot creato
    await page.request.delete(`/api/v1/calendar/template/${createdTpl.id}`, { headers: authHeaders() })
  }
})

test('calendario su iPhone: strip dei giorni ed elenco ore', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginViaLink(page)

  // Aggiunge slot martedì 14:00 - 16:00
  const addRes = await page.request.post('/api/v1/calendar/template', {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    data: JSON.stringify({
      day_of_week: 1, // Martedì
      start_time: '14:00',
      end_time: '16:00',
      materia: 'Elettromagnetismo',
      docente: 'Prof.ssa Bassi',
    }),
  })
  expect(addRes.ok()).toBeTruthy()
  const createdTpl = (await addRes.json()) as { id: number }

  try {
    // Naviga al calendario tramite tab bar iPhone
    const tabs = page.getByRole('navigation', { name: 'Navigazione' })
    await tabs.getByRole('link', { name: 'Calendario' }).click()
    await expect(page).toHaveURL(/\/calendario/)

    // Vista mobile: strip dei giorni
    const dayStrip = page.getByTestId('calendar-day-strip')
    await expect(dayStrip).toBeVisible()

    // Clic su Martedì nella strip
    const marButton = page.getByRole('button', { name: /Mar/ })
    await marButton.click()

    // L'elenco del giorno mostra Elettromagnetismo
    const eventRow = page.getByTestId('calendar-mobile-event-tpl_' + createdTpl.id)
    await expect(eventRow).toBeVisible()
    await expect(eventRow).toContainText('Elettromagnetismo', { ignoreCase: true })
    await expect(eventRow).toContainText('Prof.ssa Bassi')
  } finally {
    await page.request.delete(`/api/v1/calendar/template/${createdTpl.id}`, { headers: authHeaders() })
  }
})
