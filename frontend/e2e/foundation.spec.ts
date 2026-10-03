import { expect, test } from '@playwright/test'

import { apiGet, loginLink, loginViaLink, openLessonDetails, serverState } from './support'

type Lesson = { id: number; materia: string; titolo: string; folder_name: string; state: string | null }

test('senza sessione la SPA porta alla pagina di accesso', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByLabel('Token API')).toBeVisible()
})

test('il link monouso apre la sessione, che resta dopo la ricarica', async ({ page }) => {
  const link = await loginLink(page.request)
  await page.goto(link)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('navigation', { name: 'Navigazione' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('navigation', { name: 'Navigazione' })).toBeVisible()

  // Il link è monouso: un secondo browser riceve l'avviso nella pagina di accesso.
  const other = await page.context().browser()!.newPage()
  await other.goto(link)
  await expect(other).toHaveURL(/\/login\?error=link$/)
  await expect(other.getByText('Il link di accesso è scaduto o è già stato usato')).toBeVisible()
  await other.close()
})

test('accesso di ripiego con il token', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Token API').fill('sbagliato')
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page.getByRole('alert')).toContainText('Token non valido')
  await page.getByLabel('Token API').fill(serverState().token)
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.reload()
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  await expect(page.getByTestId('lesson-row')).toHaveCount(lessons.length)
})

test('la pagina Lezioni mostra le lezioni dell\'API, con la ricerca', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const rows = page.getByTestId('lesson-row')
  await expect(rows).toHaveCount(lessons.length)
  for (const lesson of lessons) {
    await expect(page.locator(`[data-testid=lesson-row][data-lesson-id="${lesson.id}"]`)).toBeVisible()
  }
  await expect(page.getByRole('heading', { level: 1, name: 'Lezioni' })).toBeVisible()

  // Solo la ricerca (titolo, materia, docente, data): nessun altro filtro.
  await expect(page.getByLabel('Materia', { exact: true })).toHaveCount(0)
  await page.getByLabel('Cerca').fill('rene')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('Il rene')
  await page.reload()
  await expect(page.getByLabel('Cerca')).toHaveValue('rene')
  await expect(rows).toHaveCount(1)

  // I link di prima con ?materia= restano un filtro, azzerabile.
  await page.goto('/?materia=BIOCHIMICA')
  await expect(rows).toHaveCount(lessons.filter((lesson) => lesson.materia === 'BIOCHIMICA').length)
  await expect(page.getByText('Solo Biochimica.')).toBeVisible()
  await page.getByRole('button', { name: 'Mostra tutte' }).click()
  await expect(rows).toHaveCount(lessons.length)
})

test('dalla riga si apre la lezione', async ({ page }) => {
  await loginViaLink(page)
  const [first] = await apiGet<Lesson[]>(page.request, '/lessons?materia=BIOCHIMICA')
  const row = page.locator(`[data-testid=lesson-row][data-lesson-id="${first.id}"]`)
  await row.getByRole('link', { name: 'Apri' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${first.id}$`))
  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await openLessonDetails(page)
  await expect(page.locator('[data-phase-row][data-status=VALID]')).toHaveCount(5)
  // Indietro torna alle Lezioni.
  await page.getByRole('link', { name: 'Lezioni' }).first().click()
  await expect(page).toHaveURL(/\/$/)
})

test('il tema scuro, nelle Impostazioni, resta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await page.getByRole('button', { name: 'Tema scuro' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Tema chiaro' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('esci chiude la sessione anche sul backend', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  await page.getByRole('button', { name: 'Esci' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401)
})
