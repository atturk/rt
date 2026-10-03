import { expect, test } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// Ricerca lato client nella pagina Lezioni, barra di ricerca in Recall e Immagini, sezione Review,
// barra a icone del design 4.2 (PC) e schede in basso (telefono).

type Lesson = { id: number; materia: string; data: string; pending_issues: number; titolo: string; folder_name: string }

test('la ricerca filtra sul client: nessuna richiesta all’API per tasto', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const rows = page.getByTestId('lesson-row')
  await expect(rows).toHaveCount(lessons.length)
  const queries: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/lessons?')) queries.push(r.url())
  })

  const search = page.getByLabel('Cerca')
  await expect(search).toHaveAttribute('placeholder', 'Cerca')
  const started = Date.now()
  await search.pressSequentially('farmacologia')
  await expect(rows).toHaveCount(1)
  expect(Date.now() - started).toBeLessThan(2_000) // 12 tasti compresi: nessuna attesa dell'API
  await expect(rows.first()).toContainText('Farmacologia')

  // La data si cerca anche come 19/09/2026 (la lezione di FARMACOLOGIA è del 2026-09-19).
  const farm = lessons.find((l) => l.materia === 'FARMACOLOGIA')!
  const [y, m, d] = farm.data.split('-')
  await search.fill(`${d}/${m}/${y}`)
  await expect(rows).toHaveCount(lessons.filter((l) => l.data === farm.data).length)
  await search.fill(farm.data)
  await expect(rows).toHaveCount(lessons.filter((l) => l.data === farm.data).length)
  expect(queries).toEqual([])

  // "Cerca" nell'intestazione da 52 px, sulla riga dei pulsanti Raggruppa.
  const q = (await search.boundingBox())!
  const group = (await page.getByRole('group', { name: 'Raggruppa' }).boundingBox())!
  expect(Math.abs(q.y + q.height / 2 - (group.y + group.height / 2))).toBeLessThan(2)
  expect(q.y + q.height).toBeLessThan(52)
})

test('Recall, Immagini e Review hanno la barra della dashboard', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  for (const url of ['/recall', '/immagini']) {
    await page.goto(url)
    const items = page.getByTestId('picker-lesson')
    await expect(items).toHaveCount(lessons.length)
    await page.getByLabel('Cerca').fill('rene')
    await expect(items).toHaveCount(1)
    // In Recall la materia è l'intestazione del gruppo, non la riga della lezione
    if (url === '/recall') await expect(page.locator('[data-testid=recall-subject][data-subject=FISIOLOGIA]').getByTestId('picker-lesson')).toHaveCount(1)
    else await expect(items.first()).toContainText('FISIOLOGIA')
    await page.reload()
    await expect(page.getByLabel('Cerca')).toHaveValue('rene')
    await expect(items).toHaveCount(1)
    await page.getByLabel('Cerca').fill('')
    // Stessa barra della dashboard: niente menu Materia/Stato, la materia arriva dall'URL.
    await expect(page.getByLabel('Materia', { exact: true })).toHaveCount(0)
    await expect(page.getByLabel('Raggruppa per')).toBeVisible()
    await expect(page.getByLabel('Ordina per')).toBeVisible()
    await page.goto(`${url}?materia=BIOCHIMICA`)
    await expect(items).toHaveCount(lessons.filter((l) => l.materia === 'BIOCHIMICA').length)
    await page.getByRole('button', { name: 'Tabella' }).click()
    await expect(items).toHaveCount(lessons.filter((l) => l.materia === 'BIOCHIMICA').length)
    await page.getByRole('button', { name: 'Schede' }).click()
  }
  await page.goto('/review')
  await expect(page.getByLabel('Raggruppa per')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Tabella' })).toBeVisible()
})

test('la sezione Review elenca le lezioni con issue da valutare', async ({ page }) => {
  await loginViaLink(page)
  const toReview = (await apiGet<Lesson[]>(page.request, '/lessons')).filter((l) => l.pending_issues > 0)
  expect(toReview.length).toBeGreaterThan(0)
  // Le pagine di prima restano raggiungibili dall'indirizzo e dai link.
  await page.goto('/review')
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

test('barra a icone: Nuova lezione, Lezioni, Job in corso con il badge, Impostazioni', async ({ page }) => {
  await loginViaLink(page)
  const nav = page.getByRole('navigation', { name: 'Navigazione' })
  await expect(nav.getByRole('button', { name: 'Nuova lezione' })).toBeVisible()
  await expect(nav.getByRole('link')).toHaveCount(3)
  // Ogni icona ha un nome accessibile uguale al suo tooltip.
  const lessons = nav.getByRole('link', { name: 'Lezioni' })
  await lessons.hover()
  await expect(page.getByRole('tooltip', { name: 'Lezioni' })).toBeVisible()
  await expect(lessons).toHaveAttribute('aria-current', 'page')

  const job = nav.getByRole('link', { name: 'Job in corso' })
  await expect(job.getByTestId('jobs-indicator')).toHaveCount(1)
  await job.click()
  await expect(page).toHaveURL(/\/job$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Job in corso' })).toBeVisible()
  await expect(job).toHaveAttribute('aria-current', 'page')

  // Da tastiera: Tab arriva alle voci, Invio le apre.
  await nav.getByRole('link', { name: 'Impostazioni' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/impostazioni$/)
  // Le pagine di prima restano raggiungibili: Recall, Immagini, Arricchimento accendono Lezioni.
  await page.goto('/recall')
  await expect(lessons).toHaveAttribute('aria-current', 'page')
})

test('telefono: tre schede in basso, niente barra a sinistra', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginViaLink(page)
  const tabs = page.getByRole('navigation', { name: 'Navigazione' })
  await expect(tabs).toHaveCount(1)
  await expect(tabs.getByRole('link')).toHaveCount(3)
  await expect(tabs.getByRole('button', { name: 'Nuova lezione' })).toHaveCount(0)
  const box = (await tabs.boundingBox())!
  expect(box.y + box.height).toBeCloseTo(844, 0)
  // Bersagli da 44 px sul telefono.
  for (const link of await tabs.getByRole('link').all()) expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await tabs.getByRole('link', { name: 'Job in corso' }).click()
  await expect(page).toHaveURL(/\/job$/)
  // Nessuno scorrimento orizzontale.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
