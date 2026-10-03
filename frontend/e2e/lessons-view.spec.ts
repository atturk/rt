import { expect, test } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// Pagina Lezioni del design 4.2 (schermate 01, 01b, 01c): gruppi per data, materia o docente,
// ordinamento, popup Info, selezione con lo scaricamento. Le scelte restano nel browser.

type Lesson = { id: number; materia: string; data: string; docente: string; titolo: string; folder_name: string; phases: Record<string, string> }

const ids = (rows: import('@playwright/test').Locator) => rows.evaluateAll((r) => r.map((el) => Number(el.getAttribute('data-lesson-id'))))

test('gruppi per data, materia e docente; ordinamento; le scelte restano dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  const rows = page.getByTestId('lesson-row')
  const groups = page.getByTestId('lesson-group')
  await expect(rows).toHaveCount(lessons.length)

  // Per data (di partenza): un gruppo per giorno, dalla più recente, come l'API.
  await expect(page.getByRole('button', { name: 'Per data' })).toHaveAttribute('aria-pressed', 'true')
  await expect(groups).toHaveCount(new Set(lessons.map((l) => l.data)).size)
  expect(await ids(rows)).toEqual(lessons.map((l) => l.id))
  // Nel sottotitolo la materia (la data la dice già il gruppo).
  const fis = lessons.find((l) => l.materia === 'FISIOLOGIA')!
  const subtitle = page.locator(`[data-testid=lesson-row][data-lesson-id="${fis.id}"]`).getByTestId('lesson-subtitle')
  await expect(subtitle).toContainText('Fisiologia')

  // Per materia: un gruppo per materia, la materia sparisce dal sottotitolo, Recall del gruppo.
  await page.getByRole('button', { name: 'Per materia' }).click()
  const subjects = [...new Set(lessons.map((l) => l.materia))]
  await expect(groups).toHaveCount(subjects.length)
  await expect(subtitle).not.toContainText('Fisiologia')
  const fisGroup = page.locator('[data-testid=lesson-group][data-group=FISIOLOGIA]')
  await expect(fisGroup.getByRole('heading')).toHaveText('Fisiologia')
  await expect(fisGroup.getByRole('link', { name: 'Recall su tutto il gruppo' })).toHaveAttribute('href', '/recall/materie/FISIOLOGIA')

  // Per docente: le lezioni di prova non hanno docente, un gruppo solo.
  await page.getByRole('button', { name: 'Per docente' }).click()
  await expect(groups).toHaveCount(new Set(lessons.map((l) => l.docente || '')).size)

  // Ordina: dalla meno recente.
  await page.getByRole('button', { name: 'Per data' }).click()
  await page.getByRole('button', { name: 'Ordina' }).click()
  await page.getByRole('menuitemradio', { name: 'Dalla meno recente' }).click()
  const oldest = [...lessons].sort((a, b) => a.data.localeCompare(b.data))[0]
  await expect(rows.first()).toHaveAttribute('data-lesson-id', String(oldest.id))

  await page.getByRole('button', { name: 'Per materia' }).click()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Per materia' })).toHaveAttribute('aria-pressed', 'true')
  await expect(groups).toHaveCount(subjects.length)
  await page.getByRole('button', { name: 'Ordina' }).click()
  await expect(page.getByRole('menuitemradio', { name: 'Dalla meno recente' })).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Per data' }).click()
  await page.getByRole('button', { name: 'Ordina' }).click()
  await page.getByRole('menuitemradio', { name: 'Dalla più recente' }).click()
})

test('azioni della riga sempre nello stesso ordine; popup Info si chiude con Esc, clic fuori e X', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<Lesson[]>(page.request, '/lessons?materia=BIOCHIMICA')
  const row = page.locator(`[data-testid=lesson-row][data-lesson-id="${lesson.id}"]`)
  await expect(row).toBeVisible()
  const names = await row.locator('[aria-label]').evaluateAll((els) => els.map((el) => el.getAttribute('aria-label')))
  expect(names.filter((n) => ['Info', 'Recall', 'Studio', 'Apri'].includes(n!))).toEqual(['Info', 'Recall', 'Studio', 'Apri'])

  const info = row.getByRole('button', { name: 'Info' })
  await info.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading')).toBeVisible()
  for (const term of ['Materia', 'Docente', 'Data', 'Durata', 'Unità', 'Domande', 'Costo', 'Stato']) {
    await expect(dialog.getByRole('term').filter({ hasText: new RegExp(`^${term}$`) })).toHaveCount(1)
  }
  await expect(dialog).toContainText('Biochimica')
  await expect(dialog).toContainText('nel pool')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(info).toBeFocused()

  await info.click()
  await expect(dialog).toBeVisible()
  await page.mouse.click(300, 20) // sullo sfondo, fuori dal popup
  await expect(dialog).toBeHidden()

  await info.click()
  await dialog.getByRole('button', { name: 'Chiudi' }).click()
  await expect(dialog).toBeHidden()
})

test('selezione per gruppo e scaricamento zip delle lezioni scelte', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  await page.getByRole('button', { name: 'Per materia' }).click()
  await page.getByRole('button', { name: 'Seleziona' }).click()
  const bio = lessons.filter((l) => l.materia === 'BIOCHIMICA')
  const group = page.locator('[data-testid=lesson-group][data-group=BIOCHIMICA]')
  await group.getByRole('checkbox', { name: /^Seleziona il gruppo/ }).check()
  for (const lesson of bio) await expect(page.locator(`[data-testid=lesson-row][data-lesson-id="${lesson.id}"]`).getByRole('checkbox')).toBeChecked()
  const bar = page.getByTestId('selection-bar')
  await expect(bar.getByTestId('selection-count')).toHaveText(`${bio.length} ${bio.length === 1 ? 'selezionata' : 'selezionate'}`)

  const download = page.waitForEvent('download')
  await bar.getByRole('link', { name: 'Scarica zip' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/\.zip$/)
  const response = await page.request.get(await bar.getByRole('link', { name: 'Scarica zip' }).getAttribute('href') as string)
  expect(response.status()).toBe(200)
  expect((await response.body()).subarray(0, 2).toString()).toBe('PK')

  await bar.getByRole('button', { name: 'Annulla' }).click()
  await expect(bar).toBeHidden()
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await page.getByRole('button', { name: 'Per data' }).click()
})

test('"/" porta nel campo di ricerca', async ({ page }) => {
  await loginViaLink(page)
  await expect(page.getByTestId('lesson-row').first()).toBeVisible()
  await page.locator('body').press('/')
  await expect(page.getByLabel('Cerca')).toBeFocused()
  await expect(page.getByLabel('Cerca')).toHaveValue('')
})
