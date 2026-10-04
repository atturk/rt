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

test('le pagine tolte portano a Lezioni o al pannello della lezione', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = (await apiGet<Lesson[]>(page.request, '/lessons')).filter((l) => l.pending_issues > 0)
  for (const url of ['/recall', '/immagini', '/arricchimento', '/review', '/importa']) {
    await page.goto(url)
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Lezioni' })).toBeAttached()
  }
  await page.goto('/recall/materie/BIOCHIMICA')
  await expect(page).toHaveURL(/\/\?materia=BIOCHIMICA$/)
  for (const [old, view] of [['revisione', 'verifica'], ['rilevanza', 'classificatore'], ['immagini', 'arricchimento'], ['recall/domande', 'domande']]) {
    await page.goto(`/lezioni/${lesson.id}/${old}`)
    await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}\\?panel=${view}$`))
    await expect(page.locator(`[data-testid=lesson-panel][data-view=${view}]`)).toBeVisible()
  }
  await page.goto(`/lezioni/${lesson.id}/outline`)
  await expect(page).toHaveURL(new RegExp(`/lezioni/${lesson.id}$`))
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
