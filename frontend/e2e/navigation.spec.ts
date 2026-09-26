import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// FA4: ricerca lato client, barra di ricerca in Recall e Immagini, sezione Review, voce Job con
// il badge, barra laterale riducibile.

type Lesson = { id: number; materia: string; data: string; pending_issues: number; titolo: string; folder_name: string }

const lessonsNav = (page: Page) => page.getByRole('navigation', { name: 'Lezioni per materia' })
const rail = (page: Page) => page.getByRole('navigation', { name: 'Materie' })

test('la ricerca filtra sul client: nessuna richiesta all’API per tasto', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const cards = page.getByTestId('lesson-card')
  await expect(cards).toHaveCount(lessons.length)
  const queries: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/lessons?')) queries.push(r.url())
  })

  const search = page.getByLabel('Cerca')
  await expect(search).toHaveAttribute('placeholder', 'Titolo, argomenti, materia o data')
  const started = Date.now()
  await search.pressSequentially('farmacologia')
  await expect(cards).toHaveCount(1)
  expect(Date.now() - started).toBeLessThan(2_000) // 12 tasti compresi: nessuna attesa dell'API
  await expect(cards.first()).toContainText('FARMACOLOGIA')

  // La data si cerca anche come 19/09/2026 (la lezione di FARMACOLOGIA è del 2026-09-19).
  const farm = lessons.find((l) => l.materia === 'FARMACOLOGIA')!
  const [y, m, d] = farm.data.split('-')
  await search.fill(`${d}/${m}/${y}`)
  await expect(cards).toHaveCount(lessons.filter((l) => l.data === farm.data).length)
  await search.fill(farm.data)
  await expect(cards).toHaveCount(lessons.filter((l) => l.data === farm.data).length)
  expect(queries).toEqual([])

  // Il punto interrogativo accanto a "Cerca" spiega cosa si cerca, anche al focus.
  const help = page.getByRole('button', { name: 'Informazioni sul filtro di testo' })
  await help.focus()
  await expect(page.getByRole('tooltip')).toContainText('data')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('tooltip')).toBeHidden()
})

test('Recall e Immagini hanno la stessa barra di ricerca', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  for (const url of ['/recall', '/immagini']) {
    await page.goto(url)
    const items = page.getByTestId('picker-lesson')
    await expect(items).toHaveCount(lessons.length)
    await page.getByLabel('Cerca').fill('rene')
    await expect(items).toHaveCount(1)
    await expect(items.first()).toContainText('FISIOLOGIA')
    await page.reload()
    await expect(page.getByLabel('Cerca')).toHaveValue('rene')
    await expect(items).toHaveCount(1)
    await page.getByLabel('Cerca').fill('')
    await page.getByLabel('Materia', { exact: true }).selectOption('BIOCHIMICA')
    await expect(items).toHaveCount(lessons.filter((l) => l.materia === 'BIOCHIMICA').length)
  }
})

test('la sezione Review elenca le lezioni con issue da valutare', async ({ page }) => {
  await loginViaLink(page)
  const toReview = (await apiGet<Lesson[]>(page.request, '/lessons')).filter((l) => l.pending_issues > 0)
  expect(toReview.length).toBeGreaterThan(0)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Review' }).click()
  await expect(page).toHaveURL(/\/review$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Review' })).toBeVisible()
  const cards = page.getByTestId('review-lesson')
  await expect(cards).toHaveCount(toReview.length)
  for (const lesson of toReview) {
    await expect(page.locator(`[data-testid=review-lesson][data-lesson-id="${lesson.id}"]`).getByTestId('review-count')).toHaveText(
      String(lesson.pending_issues),
    )
  }
  const target = toReview[0]
  await page.getByLabel('Cerca').fill(target.materia.toLowerCase())
  await expect(cards).toHaveCount(toReview.filter((l) => l.materia === target.materia).length)
  await page.locator(`[data-testid=review-lesson][data-lesson-id="${target.id}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${target.id}/revisione$`))
})

test('la voce Job porta il badge dei job; nessuna icona separata nell’intestazione', async ({ page }) => {
  await loginViaLink(page)
  const nav = page.getByRole('navigation', { name: 'Navigazione' })
  const job = nav.getByRole('link', { name: /^Job/ })
  await expect(job).toHaveCount(1)
  await expect(job.getByTestId('jobs-indicator')).toHaveCount(1)
  await expect(page.getByTestId('jobs-indicator')).toHaveCount(1)
  await job.click()
  await expect(page).toHaveURL(/\/job$/)
})

test('barra laterale ridotta: icone delle materie, pannello, e resta ridotta dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const [bio] = await apiGet<Lesson[]>(page.request, '/lessons?materia=BIOCHIMICA')
  // Una materia chiusa nell'elenco resta chiusa dopo riduzione ed espansione.
  await lessonsNav(page).getByText('FISIOLOGIA', { exact: true }).click()
  await expect(lessonsNav(page).locator('details:not([open])')).toHaveCount(1)

  await page.getByRole('button', { name: 'Riduci la barra laterale' }).click()
  await expect(lessonsNav(page)).toBeHidden()
  const bioButton = rail(page).getByRole('button', { name: /^BIOCHIMICA:/ })
  await expect(bioButton).toBeVisible()
  await expect(bioButton.getByTestId('subject-icon')).toHaveAttribute('data-initials', 'B')

  await bioButton.hover()
  await expect(page.getByRole('tooltip', { name: 'BIOCHIMICA' })).toBeVisible()
  await bioButton.click()
  const panel = page.getByRole('dialog', { name: 'BIOCHIMICA' })
  await expect(panel).toBeVisible()
  await expect(page.getByRole('button', { name: 'Espandi la barra laterale' })).toBeVisible() // non si espande
  await panel.getByRole('link').first().click()
  await expect(page).toHaveURL(new RegExp(`/lezioni/${bio.id}$`))
  await expect(panel).toBeHidden()

  await page.reload()
  await expect(page.locator('#rt-sidebar')).toHaveAttribute('data-collapsed', 'true')
  await expect(rail(page).getByRole('button', { name: /^BIOCHIMICA: .*lezione aperta/ })).toBeVisible()

  await page.getByRole('button', { name: 'Espandi la barra laterale' }).click()
  await expect(lessonsNav(page)).toBeVisible()
  await expect(lessonsNav(page).getByRole('link').filter({ hasText: '2026-09-05' })).toHaveClass(/bg-accent/)
})

test('barra laterale ridotta usabile da tastiera', async ({ page }) => {
  await loginViaLink(page)
  const [fis] = await apiGet<Lesson[]>(page.request, '/lessons?materia=FISIOLOGIA')
  const toggle = page.getByRole('button', { name: 'Riduci la barra laterale' })
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Espandi la barra laterale' })).toBeFocused()
  await page.keyboard.press('Tab')
  const first = rail(page).getByRole('button').first()
  await expect(first).toBeFocused()
  await expect(page.getByRole('tooltip')).toBeVisible()
  const target = rail(page).getByRole('button', { name: /^FISIOLOGIA:/ })
  for (let i = 0; i < 10 && !(await target.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press('ArrowDown')
  await expect(target).toBeFocused()
  await page.keyboard.press('Enter')
  const panel = page.getByRole('dialog', { name: 'FISIOLOGIA' })
  await expect(panel.getByRole('link').first()).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(target).toBeFocused()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/lezioni/${fis.id}$`))
})
