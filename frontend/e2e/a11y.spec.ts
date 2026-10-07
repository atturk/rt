import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

import { test, apiGet, loginViaLink } from './support'

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
    ['lezione', `/lezioni/${done}`],
    ['pannello Verifica', `/lezioni/${review}?panel=verifica`],
    ['pannello Dettagli', `/lezioni/${done}?panel=dettagli`],
    ['pannello Domande', `/lezioni/${done}?panel=domande`],
    ['pannello Classificatore', `/lezioni/${done}?panel=classificatore`],
    ['pannello Arricchimento', `/lezioni/${done}?panel=arricchimento`],
    ['sessione di ripasso', `/lezioni/${done}/sessione`],
    ['studio di una materia', '/studio/materia/BIOCHIMICA'],
    ['job', '/job'],
    ['bot', '/impostazioni/bot'],
    ['dettaglio di un job (inesistente)', '/job/non-esiste'],
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
    test.setTimeout(180_000)
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
    // Pagina della lezione (design 4.2): pannello Dettagli, menu Esporta, menu contestuale e Genera.
    const done = await lessonId(page, 'BIOCHIMICA')
    await page.goto(`/lezioni/${done}`)
    await page.getByTestId('lesson-actions').getByRole('button', { name: 'Dettagli' }).click()
    await expect(page.getByTestId('lesson-details')).toBeVisible()
    await expectNoViolations(page, 'pannello Dettagli')
    await page.keyboard.press('Escape')
    await page.getByTestId('lesson-actions').getByRole('button', { name: 'Esporta' }).click()
    await expect(page.getByRole('menu', { name: 'Esporta' })).toBeVisible()
    await expectNoViolations(page, 'menu Esporta')
    await page.keyboard.press('Escape')
    await page.getByTestId('lesson-document').locator('[data-unit-id]').first().click({ button: 'right' })
    await expect(page.getByTestId('document-menu')).toBeVisible()
    await expectNoViolations(page, 'menu contestuale del documento')
    await page.getByRole('menuitem', { name: 'Genera' }).click()
    await expect(page.getByTestId('generate-popover')).toBeVisible()
    await expectNoViolations(page, 'popup Genera')
    await page.keyboard.press('Escape')

    // Studio: lettura e domande.
    await page.goto(`/studio/lezione/${done}`)
    await expect(page.getByTestId('study-text')).toBeVisible()
    await expectNoViolations(page, 'studio, lettura')

    // Documento modificabile in place (atomic-editor), con il cursore nel testo.
    await page.goto(`/lezioni/${await lessonId(page, 'CHIRURGIA')}`)
    await page.getByTestId('lesson-document').locator('.cm-content').click()
    await expectNoViolations(page, 'documento in modifica')
    await page.keyboard.press('Escape')

    // Pagina Lezioni del design 4.2: gruppi per materia con lo sfondo, il tooltip di un'icona,
    // selezione con la barra in basso, menu Ordina e popup Nuova lezione.
    await page.goto('/')
    await page.getByRole('button', { name: 'Per materia' }).click()
    await page.mouse.move(0, 0)
    await page.getByRole('button', { name: 'Per materia' }).hover()
    await expect(page.getByRole('tooltip', { name: 'Per materia' })).toBeVisible()
    await expectNoViolations(page, 'lezioni per materia con un tooltip')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Seleziona' }).click()
    await page.getByTestId('lesson-group').first().getByRole('checkbox', { name: /^Seleziona il gruppo/ }).check()
    await expect(page.getByTestId('selection-bar')).toBeVisible()
    await expectNoViolations(page, 'selezione delle lezioni')
    await page.getByRole('button', { name: 'Annulla' }).click()
    await page.getByRole('button', { name: 'Ordina' }).click()
    await expect(page.getByRole('menu')).toBeVisible()
    await expectNoViolations(page, 'menu Ordina')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Per data' }).click()
    await page.getByRole('button', { name: 'Nuova lezione' }).click()
    await expect(page.getByTestId('drop-zone')).toBeVisible()
    await expectNoViolations(page, 'popup Nuova lezione')
    await page.keyboard.press('Escape')

    // Telefono: schede in basso e ricerca aperta.
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: 'Mostra la ricerca' }).click()
    await expect(page.getByLabel('Cerca', { exact: true })).toBeVisible()
    await expectNoViolations(page, 'lezioni sul telefono')
    await page.setViewportSize({ width: 1280, height: 720 })
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
