import { expect, test } from '@playwright/test'

import { apiGet, loginLink, loginViaLink, serverState } from './support'

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
  await expect(page.getByRole('navigation', { name: 'Lezioni per materia' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('navigation', { name: 'Lezioni per materia' })).toBeVisible()

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
  await expect(page.getByTestId('lesson-card')).toHaveCount(2)
})

test('la dashboard mostra le lezioni dell\'API, con filtri', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const cards = page.getByTestId('lesson-card')
  await expect(cards).toHaveCount(lessons.length)
  for (const lesson of lessons) {
    await expect(page.locator(`[data-testid=lesson-card][data-lesson-id="${lesson.id}"]`)).toBeVisible()
  }
  const sidebar = page.getByRole('navigation', { name: 'Lezioni per materia' })
  await expect(sidebar.getByText('BIOCHIMICA')).toBeVisible()
  await expect(sidebar.getByText('FISIOLOGIA')).toBeVisible()

  await page.getByLabel('Materia', { exact: true }).selectOption('FISIOLOGIA')
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('Il rene')
  await page.reload()
  await expect(page.getByLabel('Materia', { exact: true })).toHaveValue('FISIOLOGIA')
  await expect(cards).toHaveCount(1)

  await page.getByLabel('Materia', { exact: true }).selectOption('')
  await page.getByLabel('Stato', { exact: true }).selectOption('completato')
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('BIOCHIMICA')

  await page.getByLabel('Stato', { exact: true }).selectOption('')
  await page.getByLabel('Cerca').fill('rene')
  await expect(cards).toHaveCount(1)
})

test('dalla barra laterale si apre la lezione', async ({ page }) => {
  await loginViaLink(page)
  const [first] = await apiGet<Lesson[]>(page.request, '/lessons?materia=BIOCHIMICA')
  await page.getByRole('navigation', { name: 'Lezioni per materia' }).getByRole('link').filter({ hasText: '2026-09-05' }).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${first.id}$`))
  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByLabel('Stato delle fasi').locator('[data-status=VALID]')).toHaveCount(5)
})

test('il tema scuro resta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('button', { name: 'Tema scuro' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Tema chiaro' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('esci chiude la sessione anche sul backend', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('button', { name: 'Esci' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401)
})
