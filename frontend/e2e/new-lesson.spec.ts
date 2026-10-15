import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink, tinyPdf } from './support'

// Popup Nuova lezione dalla barra a icone (schermate 00 e 00b): con l'audio materia, docente,
// data e Avvia, poi la pagina della lezione con l'avanzamento; con lo zip solo Importa.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; state: string; lesson_id: number | null; payload: { options?: Record<string, unknown> } }
type Lesson = { id: number; materia: string; docente: string; data: string; folder_name: string }

test('audio: materia, docente, data di oggi, Avvia e si arriva alla lezione con l’avanzamento', async ({ page }) => {
  test.setTimeout(3 * LONG)
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('button', { name: 'Nuova lezione' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('drop-zone')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Avvia' })).toBeVisible()

  await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles(AUDIO)
  await expect(dialog.getByTestId('chosen-files')).toHaveAttribute('data-kind', 'audio')
  await expect(dialog.getByTestId('chosen-files')).toContainText('demo_lecture.wav')
  const today = await page.evaluate(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  })
  await expect(dialog.getByLabel(/^Data/)).toHaveValue(today)
  await expect(dialog.getByText('Data · oggi')).toBeVisible()
  await dialog.getByLabel('Materia').fill('EMBRIOLOGIA')
  await dialog.getByLabel('Docente').fill('Neri')
  await dialog.getByRole('button', { name: 'Avvia' }).click()

  // Prima la pagina d'attesa del job, poi (appena il setup crea la lezione) la lezione.
  await expect(page).toHaveURL(/\/lezioni\/(nuova\/[0-9a-f-]+|\d+)$/)
  await expect(page).toHaveURL(/\/lezioni\/\d+$/, { timeout: LONG })
  const lessonId = Number(page.url().split('/lezioni/')[1])
  const lesson = await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)
  expect(lesson).toMatchObject({ materia: 'EMBRIOLOGIA', docente: 'Neri', data: today })
  await expect(page.getByTestId('lesson-path')).toContainText(/^Embriologia · .+ · Neri$/)

  // Avanzamento a due barre finché il job è attivo; poi il job si chiude (qui lo annulliamo).
  const [job] = (await apiGet<Job[]>(page.request, `/jobs?lesson_id=${lessonId}`)).filter((j) => ['queued', 'running', 'waiting_for_decision'].includes(j.state))
  if (job) {
    // In corso: le due barre; ferma sulla scaletta: il riquadro "Scaletta da approvare" (C4).
    await expect(page.getByTestId('phase-progress').or(page.getByTestId('outline-approval')).first()).toBeVisible()
    const res = await page.request.post(`/api/v1/jobs/${job.id}/cancel`, { headers: authHeaders() })
    expect(res.ok()).toBeTruthy()
    await expect.poll(async () => (await apiGet<Job>(page.request, `/jobs/${job.id}`)).state, { timeout: LONG }).toBe('cancelled')
  }

  // Elimina (il popup Info non c'è più; nel giro 2 l'eliminazione torna nel pannello Dettagli).
  const del = await page.request.delete(`/api/v1/lessons/${lessonId}`, { headers: authHeaders() })
  expect(del.ok()).toBeTruthy()
  await page.goto('/')
  await expect(page.locator(`[data-testid=lesson-row][data-lesson-id="${lessonId}"]`)).toHaveCount(0)
  expect((await page.request.get(`/api/v1/lessons/${lessonId}`, { headers: authHeaders() })).status()).toBe(404)
})

test('zip: niente campi, Importa usa /lessons/import-zip', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<Lesson[]>(page.request, '/lessons?materia=BIOCHIMICA')
  const zip = await page.request.get(`/api/v1/lesson-exports?ids=${lesson.id}&format=zip&name=prova`, { headers: authHeaders() })
  expect(zip.ok()).toBeTruthy()

  await page.getByRole('button', { name: 'Nuova lezione' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles({ name: 'lezione.zip', mimeType: 'application/zip', buffer: await zip.body() })
  await expect(dialog.getByTestId('chosen-files')).toHaveAttribute('data-kind', 'zip')
  await expect(dialog.getByLabel('Materia')).toHaveCount(0)
  await expect(dialog.getByLabel('Docente')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Avvia' })).toHaveCount(0)

  const posted = page.waitForRequest((r) => r.method() === 'POST' && r.url().includes('/api/v1/lessons/import-zip'))
  await dialog.getByRole('button', { name: 'Importa' }).click()
  await posted
  // Lo ZIP di gruppo (anche di una sola lezione) si espande; la lezione c'è già e il popup lo dice.
  await expect(dialog.getByRole('list', { name: "Esito dell'importazione" })).toContainText('già presente', { timeout: LONG })
  await expect(dialog.getByTestId('import-summary')).toHaveText('0 importate, 1 già presenti, 0 rifiutate')
  // A job finito niente reimport: "Importa" lascia il posto a "Chiudi".
  await expect(dialog.getByRole('button', { name: 'Importa' })).toHaveCount(0)
  await expect(dialog.getByRole('form', { name: 'Nuova lezione' }).getByRole('button', { name: 'Chiudi' })).toBeVisible()

  // Esc chiude.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('più audio: la lista mostra l’ordine e lo si cambia con le frecce sulla maniglia', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('button', { name: 'Nuova lezione' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  // La seconda parte basta che sia un file audio: il popup non la apre, la mette solo in coda.
  await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles([
    { name: 'demo_lecture.wav', mimeType: 'audio/wav', buffer: readFileSync(AUDIO) },
    { name: 'parte2.wav', mimeType: 'audio/wav', buffer: readFileSync(AUDIO) },
  ])
  const rows = dialog.getByTestId('audio-order-item')
  await expect(rows).toHaveCount(2)
  await expect(rows.first()).toContainText('demo_lecture.wav')
  await dialog.getByRole('button', { name: /^Riordina parte2\.wav/ }).press('ArrowUp')
  await expect(rows.first()).toContainText('parte2.wav')
  await expect(dialog.getByTestId('chosen-files')).toContainText("diventano un'unica registrazione")
})

test('trascinamento su tutta la pagina: velo Rilascia per importare e apertura popup (UI3)', async ({ page }) => {
  await loginViaLink(page)

  // 1. Simula dragenter con un file audio accettato
  await page.evaluate(() => {
    const dt = new DataTransfer()
    const file = new File(['fake audio'], 'lezione.mp3', { type: 'audio/mpeg' })
    dt.items.add(file)
    window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, cancelable: true }))
    window.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, cancelable: true }))
  })

  const veil = page.getByTestId('global-drop-veil')
  await expect(veil).toBeVisible()
  await expect(veil).toContainText('Rilascia per importare')

  // 2. Simula drop sulla finestra
  await page.evaluate(() => {
    const dt = new DataTransfer()
    const file = new File(['fake audio'], 'lezione.mp3', { type: 'audio/mpeg' })
    dt.items.add(file)
    window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, cancelable: true }))
  })

  // Il velo scompare e si apre il popup Nuova lezione con il file caricato
  await expect(veil).toHaveCount(0)
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('chosen-files')).toContainText('lezione.mp3')

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})


test('più audio uniti con un PDF: la lezione ha il player', async ({ page }) => {
  // L'audio unito sta fra le fonti (sources/<id>/): il player deve trovarlo (4.2.6b2.1).
  await loginViaLink(page)
  const materia = 'PLAYER UNITO'
  const res = await page.request.post('/api/v1/lessons', {
    headers: authHeaders(),
    multipart: {
      audio: { name: 'parte1.wav', mimeType: 'audio/wav', buffer: readFileSync(AUDIO) },
      materiali: { name: 'slide.pdf', mimeType: 'application/pdf', buffer: tinyPdf() },
      date: '2026-10-14', materia, mock: 'true', unisci: 'true', run: 'false',
    },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  type Lesson = { id: number; materia: string; has_audio?: boolean }
  await expect.poll(async () => (await apiGet<Lesson[]>(page.request, '/lessons')).find((l) => l.materia === materia)?.id,
    { timeout: LONG }).toBeTruthy()
  const id = (await apiGet<Lesson[]>(page.request, '/lessons')).find((l) => l.materia === materia)!.id
  await expect.poll(async () => (await apiGet<Lesson>(page.request, `/lessons/${id}`)).has_audio, { timeout: LONG }).toBe(true)
  await page.goto(`/lezioni/${id}`)
  await expect(page.getByTestId('audio-player')).toBeVisible()
})
