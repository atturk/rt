import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, tinyPdf } from './support'

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
    await expect(weekLabel).not.toHaveText('Caricamento…')

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

test('calendario: icona + nel popup ora apre popup di import con data e ora preselezionate (UI1)', async ({ page }) => {
  await loginViaLink(page)

  // Crea uno slot di prova nella settimana tipo (giovedì 08:30 - 10:30)
  const addRes = await page.request.post('/api/v1/calendar/template', {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    data: JSON.stringify({
      day_of_week: 3,
      start_time: '08:30',
      end_time: '10:30',
      materia: 'Chirurgia Generale',
      docente: 'Prof. De Luca',
    }),
  })
  expect(addRes.ok()).toBeTruthy()
  const createdTpl = (await addRes.json()) as { id: number }
  const key = 'tpl_' + createdTpl.id

  try {
    await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Calendario' }).click()
    await expect(page).toHaveURL(/\/calendario/)

    const slot = page.getByTestId('calendar-event-' + key).first()
    await expect(slot).toBeVisible()
    await slot.click()

    const eventPopup = page.getByTestId('calendar-event-popup')
    await expect(eventPopup).toBeVisible()
    await expect(eventPopup.getByText('Nessuna registrazione')).toBeVisible()

    const plusBtn = eventPopup.getByRole('button', { name: "Importa una lezione per quest'ora" })
    await expect(plusBtn).toBeVisible()
    await plusBtn.click()

    // Il popup evento si chiude e si apre il popup Nuova lezione
    await expect(eventPopup).toHaveCount(0)
    const newLessonDialog = page.getByTestId('new-lesson')
    await expect(newLessonDialog).toBeVisible()

    // La materia dello slot è preselezionata
    await expect(newLessonDialog.getByLabel('Materia')).toHaveValue('Chirurgia Generale')
    await page.keyboard.press('Escape')
    await expect(newLessonDialog).toHaveCount(0)
  } finally {
    await page.request.delete(`/api/v1/calendar/template/${createdTpl.id}`, { headers: authHeaders() })
  }
})


test('calendario: seguita senza lezione resta importabile e viene collegata', async ({ page }) => {
  test.setTimeout(180_000)
  await loginViaLink(page)
  const created = await page.request.post('/api/v1/calendar/template', {
    headers: authHeaders(), data: { day_of_week: 3, start_time: '07:00', end_time: '08:00', materia: 'Prova Seguita' },
  })
  expect(created.ok()).toBeTruthy()
  const { id } = await created.json() as { id: number }
  const key = `tpl_${id}`
  let lessonId: number | undefined
  try {
    await page.goto('/calendario')
    await page.getByTestId(`calendar-event-${key}`).click()
    const popup = page.getByTestId('calendar-event-popup')
    await popup.getByRole('button', { name: 'Seguita', exact: true }).click()
    await expect(popup.getByRole('button', { name: "Importa una lezione per quest'ora" })).toBeVisible()
    await popup.getByRole('button', { name: "Importa una lezione per quest'ora" }).click()
    const dialog = page.getByTestId('new-lesson')
    await expect(dialog.getByLabel('Materia')).toHaveValue('Prova Seguita')
    const date = await dialog.getByLabel(/^Data/).inputValue()
    await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles({
      name: 'seguita.pdf', mimeType: 'application/pdf', buffer: tinyPdf(),
    })
    const posted = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/lessons')
    await dialog.getByRole('button', { name: 'Avvia' }).click()
    const imported = await posted
    expect(imported.ok(), await imported.text()).toBeTruthy()
    await expect.poll(async () => {
      const day = await apiGet<{ events: { key: string; lesson?: { id: number }; is_recorded: boolean; status: string }[] }>(page.request, `/calendar/day?date=${date}`)
      const event = day.events.find((event) => event.key === key)
      lessonId = event?.lesson?.id
      return event?.is_recorded && event.status === 'seguita'
    }, { timeout: 120_000 }).toBe(true)
  } finally {
    if (lessonId) {
      const jobs = await apiGet<{ id: string; state: string }[]>(page.request, `/jobs?lesson_id=${lessonId}`)
      for (const job of jobs.filter((job) => ['queued', 'running', 'waiting_for_decision'].includes(job.state))) {
        await page.request.post(`/api/v1/jobs/${job.id}/cancel`, { headers: authHeaders() })
        await expect.poll(async () => (await apiGet<{ state: string }>(page.request, `/jobs/${job.id}`)).state).toBe('cancelled')
      }
      await page.request.delete(`/api/v1/lessons/${lessonId}`, { headers: authHeaders() })
    }
    await page.request.delete(`/api/v1/calendar/template/${id}`, { headers: authHeaders() })
  }
})

test('calendario: suggerimento ordinato e nota immediata senza perdere il clic', async ({ page }) => {
  await loginViaLink(page)
  const created = await page.request.post('/api/v1/calendar/template', {
    headers: authHeaders(), data: { day_of_week: 0, start_time: '12:30', end_time: '14:30', materia: 'Prova Nota', docente: 'Prof. Nota' },
  })
  expect(created.ok()).toBeTruthy()
  const { id } = await created.json() as { id: number }
  const key = `tpl_${id}`
  try {
    const week = await apiGet<{ days: { events: { key: string; date: string }[] }[] }>(page.request, '/calendar/week')
    const event = week.days.flatMap(day => day.events).find(event => event.key === key)!
    expect(event).toBeTruthy()
    const saved = await page.request.post('/api/v1/calendar/entry-state', {
      headers: authHeaders(), data: { date: event.date, entry_key: key, template_entry_id: id, note: 'Aula 2\nPortare gli appunti' },
    })
    expect(saved.ok()).toBeTruthy()
    await page.goto('/calendario')
    const block = page.getByTestId(`calendar-event-${key}`)
    await expect(block).toBeVisible()
    await block.hover({ position: { x: 20, y: 10 } })
    const tooltip = page.getByRole('tooltip')
    await expect(tooltip).toContainText('Prof. Nota')
    await expect(tooltip.locator('.font-semibold')).toHaveText('Prova Nota')
    await expect(tooltip.locator('.font-mono')).toHaveText('12:30–14:30')
    await expect(tooltip.locator('.line-clamp-4')).toHaveText('Aula 2\nPortare gli appunti')
    await page.mouse.move(0, 0)
    await expect(tooltip).toHaveCount(0)
    const note = block.getByTestId(`calendar-note-${key}`)
    await note.hover()
    await expect(tooltip).toHaveText('Aula 2\nPortare gli appunti')
    await page.waitForTimeout(700)
    await expect(tooltip).toHaveCount(1)
    await expect(tooltip).toHaveText('Aula 2\nPortare gli appunti')
    expect(await block.locator('button').count()).toBe(0)
    await note.click()
    await expect(page.getByTestId('calendar-event-popup')).toBeVisible()
    await expect(tooltip).toHaveCount(0)
  } finally {
    await page.request.delete(`/api/v1/calendar/template/${id}`, { headers: authHeaders() })
  }
})

test('calendario: aggiunge un’ora solo nelle settimane scelte', async ({ page }) => {
  await loginViaLink(page)
  const week = await apiGet<{ start_date: string }>(page.request, '/calendar/week')
  const shift = (days: number) => new Date(Date.parse(`${week.start_date}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10)
  const from = week.start_date, last = shift(7), to = shift(14)
  let createdId: number | undefined
  try {
    await page.goto('/calendario')
    await page.getByRole('button', { name: 'Modifica orario' }).focus()
    await page.getByRole('button', { name: 'Modifica la settimana tipo in un intervallo di settimane' }).click()
    const popup = page.getByRole('dialog', { name: 'Intervallo di settimane' })
    await popup.locator(`[data-week="${from}"]`).click()
    if (!await popup.locator(`[data-week="${last}"]`).count()) await popup.getByRole('button', { name: 'Anno successivo' }).click()
    await popup.locator(`[data-week="${last}"]`).click()
    await test.info().attach('Intervallo di settimane', { body: await popup.screenshot(), contentType: 'image/png' })
    await popup.getByRole('button', { name: 'Modifica queste settimane' }).click()
    await expect(popup).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cambia intervallo di settimane' })).toBeVisible()
    await page.getByRole('button', { name: 'Aggiungi alle 08:30', exact: true }).first().click()
    const add = page.getByRole('dialog', { name: 'Aggiungi ora' })
    await add.getByLabel('Materia').fill('Prova Intervallo')
    const response = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/v1/calendar/template')
    await add.getByRole('button', { name: 'Aggiungi', exact: true }).click()
    const saved = await response
    expect(saved.ok()).toBeTruthy()
    const created = await saved.json() as { id: number; valid_from: string; valid_to: string }
    createdId = created.id
    expect(created.valid_from).toBe(from)
    expect(created.valid_to).toBe(to)
    const block = page.getByTestId(`calendar-event-tpl_${createdId}`)
    await expect(block).toBeVisible()
    await page.getByRole('button', { name: 'Settimana successiva' }).click()
    await expect(block).toBeVisible()
    await page.getByRole('button', { name: 'Settimana successiva' }).click()
    await expect(page.getByText("Fuori dall'intervallo scelto")).toBeVisible()
    await expect(block).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Aggiungi alle/ })).toHaveCount(0)
    const outside = await apiGet<{ days: { events: { key: string }[] }[] }>(page.request, `/calendar/week?date=${to}`)
    expect(outside.days.flatMap(day => day.events).some(event => event.key === `tpl_${createdId}`)).toBe(false)
  } finally {
    if (createdId) await page.request.delete(`/api/v1/calendar/template/${createdId}`, { headers: authHeaders() })
  }
})

test('inizio periodo, avviso lezioni mancanti e collegamento al calendario', async ({ page }) => {
  await loginViaLink(page)
  const date = new Date()
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7) - 14)
  const iso = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  const response = await page.request.post('/api/v1/calendar/template', { headers: authHeaders(), data: { day_of_week: 0, start_time: '09:00', end_time: '10:00', materia: 'STUDIO', valid_from: iso } })
  expect(response.ok()).toBeTruthy()
  const template = await response.json() as { id: number }
  try {
    await page.goto(`/calendario?data=${iso}`)
    await page.getByRole('button', { name: 'Riepilogo della settimana' }).click()
    await page.getByRole('button', { name: 'Inizio del periodo', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Inizio del periodo ✓' })).toBeVisible()
    await page.goto('/')
    await page.getByRole('button', { name: 'Per materia', exact: true }).click()
    const header = page.getByRole('heading', { name: /^Studio(?:\s|$)/ })
    await header.getByRole('button', { name: /lezioni mancanti/ }).click()
    const link = page.getByTestId('missing-lessons-popup').locator(`a[href="/calendario?data=${iso}&evento=tpl_${template.id}"]`)
    await link.click()
    await expect(page).toHaveURL(new RegExp(`data=${iso}&evento=tpl_${template.id}`))
    await expect(page.getByTestId(`calendar-event-tpl_${template.id}`).first()).toHaveClass(/rt-media-flash/)
  } finally {
    await page.request.put('/api/v1/calendar/period-start', { headers: authHeaders(), data: { date: null } })
    await page.request.delete(`/api/v1/calendar/template/${template.id}`, { headers: authHeaders() })
  }
})
