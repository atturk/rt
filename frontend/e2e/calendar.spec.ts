import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

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

test('calendario: modifica di un\'ora solo per questa settimana', async ({ page }) => {
  await loginViaLink(page)

  // Ora di prova nella settimana tipo (mercoledì 10:30 - 12:30)
  const addRes = await page.request.post('/api/v1/calendar/template', {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    data: JSON.stringify({
      day_of_week: 2,
      start_time: '10:30',
      end_time: '12:30',
      materia: 'Prova Modifica Ora',
      docente: 'Prof. Verdi',
    }),
  })
  expect(addRes.ok()).toBeTruthy()
  const createdTpl = (await addRes.json()) as { id: number }
  const key = 'tpl_' + createdTpl.id

  type WeekEvent = { key: string; end_time: string; is_modified: boolean; override_id?: number | null }
  const readEvent = async () => {
    const week = (await apiGet<{ days: { events: WeekEvent[] }[] }>(page.request, '/calendar/week'))
    return week.days.flatMap((d) => d.events).find((e) => e.key === key)
  }

  try {
    await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Calendario' }).click()
    await expect(page).toHaveURL(/\/calendario/)

    const slot = page.getByTestId('calendar-event-' + key)
    await expect(slot).toContainText('10:30–12:30')
    await expect(slot).toContainText('Prof. Verdi')

    // Modalità modifica "solo questa settimana": il clic sull'ora apre il popup precompilato
    // Le due opzioni compaiono al passaggio o al focus sulla matita
    await page.getByRole('button', { name: 'Modifica orario' }).focus()
    await page.getByRole('button', { name: 'Modifica solo questa settimana' }).click()
    await slot.click()
    const popup = page.getByTestId('calendar-edit-event-popup')
    await expect(popup).toBeVisible()
    await expect(popup.getByLabel('Materia')).toHaveValue('Prova Modifica Ora')
    await expect(popup.getByLabel('Inizio')).toHaveValue('10:30')
    await popup.getByLabel('Fine').fill('13:00')
    await popup.getByRole('button', { name: 'Salva' }).click()
    await expect(popup).toHaveCount(0)

    await expect(slot).toContainText('10:30–13:00')
    await expect.poll(async () => (await readEvent())?.end_time).toBe('13:00')
    expect((await readEvent())?.is_modified).toBe(true)

    // La settimana tipo resta com'era
    const tpl = await apiGet<{ id: number; end_time: string }[]>(page.request, '/calendar/template')
    expect(tpl.find((t) => t.id === createdTpl.id)?.end_time).toBe('12:30')
  } finally {
    const ev = await readEvent()
    if (ev?.override_id) {
      await page.request.delete(`/api/v1/calendar/override/${ev.override_id}`, { headers: authHeaders() })
    }
    await page.request.delete(`/api/v1/calendar/template/${createdTpl.id}`, { headers: authHeaders() })
  }
})
