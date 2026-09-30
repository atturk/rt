import { expect, test } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// Pagina Lezioni: vista a schede o tabella, ordinamento e raggruppamento, ricordati nel browser.

type Lesson = { id: number; materia: string; data: string }

test('tabella ordinabile, gruppi per materia e preferenze che restano dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  await expect(page.getByTestId('lesson-card')).toHaveCount(lessons.length)
  await expect(page.getByTestId('lesson-count')).toContainText(`${lessons.length} lezioni`)

  await page.getByRole('button', { name: 'Tabella' }).click()
  const rows = page.getByTestId('lesson-row')
  await expect(rows).toHaveCount(lessons.length)
  await expect(page.getByTestId('lesson-card')).toHaveCount(0)
  // Di partenza: dalla più recente, come l'API.
  expect(await rows.evaluateAll((r) => r.map((el) => Number(el.getAttribute('data-lesson-id'))))).toEqual(lessons.map((l) => l.id))

  // Clic sull'intestazione Data: dalla meno recente.
  await page.getByRole('button', { name: 'Data', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: 'Data' })).toHaveAttribute('aria-sort', 'ascending')
  const ascending = [...lessons].sort((a, b) => a.data.localeCompare(b.data))
  expect(await rows.first().getAttribute('data-lesson-id')).toBe(String(ascending[0].id))

  await page.getByLabel('Raggruppa per').selectOption('materia')
  const subjects = [...new Set(lessons.map((l) => l.materia))]
  await expect(page.getByTestId('lesson-group')).toHaveCount(subjects.length)
  const first = page.getByTestId('lesson-group-toggle').first()
  await first.click()
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await expect(rows).toHaveCount(lessons.length - lessons.filter((l) => l.materia === [...subjects].sort()[0]).length)

  // I filtri si combinano con i gruppi; "Azzera filtri" li toglie.
  await page.getByLabel('Cerca').fill('rene')
  await expect(page.getByTestId('lesson-count')).toContainText(`1 di ${lessons.length} lezioni`)
  await page.getByRole('button', { name: 'Azzera filtri' }).click()
  await expect(page.getByLabel('Cerca')).toHaveValue('')

  await page.reload()
  await expect(page.getByRole('button', { name: 'Tabella' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Raggruppa per')).toHaveValue('materia')
  await expect(page.getByLabel('Ordina per')).toHaveValue('data')
  await expect(page.getByTestId('lesson-group-toggle').first()).toHaveAttribute('aria-expanded', 'false')
})

test('"/" porta nel campo di ricerca', async ({ page }) => {
  await loginViaLink(page)
  await expect(page.getByTestId('lesson-card').first()).toBeVisible()
  await page.locator('body').press('/')
  await expect(page.getByLabel('Cerca')).toBeFocused()
  await expect(page.getByLabel('Cerca')).toHaveValue('')
})
