import { expect, type Page } from '@playwright/test'
import { test, apiGet, loginViaLink } from './support'

type Lesson = { id: number; materia: string }

async function getLesson(page: Page, materia: string) {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

test('conto alla rovescia nella lettura veloce: impostare 2 s, Play, vedere il conto e poi la lettura (4.3.3b3 piano 7)', async ({ page }) => {
  test.setTimeout(90_000)
  await loginViaLink(page)
  const l = await getLesson(page, 'STUDIO')

  await page.goto(`/studio/lezione/${l.id}`)
  await expect(page.getByTestId('study-text')).toBeVisible()

  // Apri lettura veloce
  await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
  const reader = page.getByTestId('speed-reader')
  await expect(reader).toBeVisible()

  // Apri le impostazioni della lettura veloce
  await page.getByRole('button', { name: 'Impostazioni della lettura veloce', exact: true }).click()
  const settings = page.getByTestId('speed-reader-settings')
  await expect(settings).toBeVisible()

  // Imposta conto alla rovescia a 2 s
  const countdownSlider = settings.getByLabel('Conto alla rovescia')
  await countdownSlider.fill('2')
  await expect(settings).toContainText('2 s')

  // Chiudi le impostazioni
  await page.getByRole('button', { name: 'Chiudi le impostazioni', exact: true }).click()
  await expect(settings).not.toBeVisible()

  // Clicca Avvia (Play)
  await page.getByRole('button', { name: 'Avvia', exact: true }).click()

  // Verifica che il conto alla rovescia sia visibile e mostri 2 poi 1
  const countdown = page.getByTestId('speed-reader-countdown')
  await expect(countdown).toBeVisible()
  await expect(countdown).toHaveText('2')

  // Poi scala a 1
  await expect(countdown).toHaveText('1')

  // Dopo la fine del conto, il conto scompare e la lettura è in corso
  await expect(countdown).not.toBeVisible()
  const word = page.getByTestId('speed-reader-word')
  await expect(word).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pausa', exact: true })).toBeVisible()
})
