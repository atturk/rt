import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink } from './support'

// Accessibilità di base (RT4-F7): axe con le regole WCAG 2 A/AA su ogni pagina, nei due temi.
// Controlla etichette, nomi dei pulsanti, ruoli, focus visibile e contrasto dei colori.

type Lesson = { id: number; materia: string }

async function lessonId(page: Page, materia: string) {
  const [lesson] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return lesson.id
}

async function pages(page: Page): Promise<[string, string][]> {
  const done = await lessonId(page, 'BIOCHIMICA')
  const review = await lessonId(page, 'FARMACOLOGIA')
  return [
    ['dashboard', '/'],
    ['review (elenco)', '/review'],
    ['recall (elenco)', '/recall'],
    ['immagini (elenco)', '/immagini'],
    ['lezione', `/lezioni/${done}`],
    ['revisione', `/lezioni/${review}/revisione`],
    ['revisione per gravità', `/lezioni/${review}/revisione?ordine=gravita`],
    ['outline', `/lezioni/${done}/outline`],
    ['recall', `/lezioni/${done}/recall`],
    ['immagini', `/lezioni/${done}/immagini`],
    ['importa', '/importa'],
    ['job', '/job'],
    ['bot', '/bot'],
    ['impostazioni', '/impostazioni'],
    ['modelli', '/impostazioni/modelli'],
    ['chiavi', '/impostazioni/chiavi'],
    ['costi', '/impostazioni/costi'],
    ['ricerca web', '/impostazioni/ricerca-web'],
    ['configurazione guidata', '/impostazioni/configurazione'],
    ['pagina inesistente', '/non-esiste'],
  ]
}

async function expectNoViolations(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join('\n  ')}`,
  )
  expect(results.passes.length, `axe non ha controllato "${name}"`).toBeGreaterThan(3)
  expect(summary, `violazioni di accessibilità in "${name}"`).toEqual([])
}

for (const theme of ['light', 'dark'] as const) {
  test(`accessibilità: nessuna violazione axe, tema ${theme === 'dark' ? 'scuro' : 'chiaro'}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('rt-theme', t), theme)
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expectNoViolations(page, 'accesso')

    await loginViaLink(page)
    await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark)/)
    for (const [name, url] of await pages(page)) {
      await page.goto(url)
      await expect(page.locator('main')).toBeVisible()
      await expect(page.getByText(/^Carico/)).toHaveCount(0)
      await expectNoViolations(page, name)
    }
    // Slider della velocità aperto nel player.
    await page.goto(`/lezioni/${await lessonId(page, 'BIOCHIMICA')}`)
    await page.getByRole('button', { name: /^Velocità di riproduzione/ }).click()
    await expect(page.getByRole('slider', { name: 'Velocità di riproduzione' })).toBeVisible()
    await expectNoViolations(page, 'velocità del player')

    // Anteprima in modifica (RT4-FA3) con gli avvisi prima di entrare.
    await page.goto(`/lezioni/${await lessonId(page, 'CHIRURGIA')}`)
    await page.getByRole('button', { name: "Modifica l'anteprima" }).click()
    const notice = page.getByRole('dialog', { name: "Modifica dell'anteprima" })
    if (await notice.isVisible()) {
      await expectNoViolations(page, "avvisi della modifica dell'anteprima")
      await notice.getByRole('button', { name: 'Modifica' }).click()
    }
    await expect(page.getByTestId('markdown-editor')).toBeVisible()
    await expect(page.locator('.rt-document-edit-preview')).toHaveCount(0)
    await expectNoViolations(page, "editor a tutta larghezza")
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('markdown-editor')).toHaveCount(0)

    // Barra laterale ridotta con il pannello di una materia aperto e il suggerimento del nome.
    await page.goto('/')
    await page.getByRole('button', { name: 'Riduci la barra laterale' }).click()
    const subject = page.getByRole('navigation', { name: 'Materie' }).getByRole('button').first()
    await subject.focus()
    await expect(page.getByRole('tooltip')).toBeVisible()
    await expectNoViolations(page, 'barra laterale ridotta')
    await subject.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expectNoViolations(page, 'pannello della materia')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Espandi la barra laterale' }).click()
  })
}

test('accessibilità: la navigazione da tastiera mostra il focus', async ({ page }) => {
  await loginViaLink(page)
  await page.keyboard.press('Tab')
  const focused = page.locator(':focus')
  await expect(focused).toHaveCount(1)
  const outline = await focused.evaluate((el) => {
    const s = getComputedStyle(el)
    return { outline: s.outlineStyle, width: s.outlineWidth, shadow: s.boxShadow }
  })
  expect(outline.outline !== 'none' || outline.shadow !== 'none', JSON.stringify(outline)).toBeTruthy()
})
