import { expect, type Page } from '@playwright/test'
import { test, apiGet, loginViaLink } from './support'

type Lesson = { id: number; materia: string }

async function getLesson(page: Page, materia: string) {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

test('formule nella lettura veloce: formula corta scala 1, formula lunga adattata e centrata a 1280 e 390 px (4.3.3b3 piano 6)', async ({ page }) => {
  test.setTimeout(90_000)
  await loginViaLink(page)
  const l = await getLesson(page, 'STUDIO')

  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto(`/studio/lezione/${l.id}`)
    await expect(page.getByTestId('study-text')).toBeVisible()

    // Inseriamo nell'unità una formula corta e una molto lunga
    await page.evaluate(() => {
      const container = document.querySelector('[data-testid="study-text"]')
      if (container) {
        const p = document.createElement('p')
        p.id = 'test-math-container'
        p.innerHTML = 'Formule. <math id="short-math"><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></math> corta. <math id="long-math" display="block"><mrow><mi>Q</mi><mo>=</mo><msup><mn>10</mn><mn>-6</mn></msup><msubsup><mo>∫</mo><mn>-3</mn><mn>3</mn></msubsup><msubsup><mo>∫</mo><mn>-3</mn><mn>3</mn></msubsup><mn>4</mn><msup><mi>y</mi><mn>2</mn></msup><mspace width="0.167em"></mspace><mi>d</mi><mi>x</mi><mspace width="0.167em"></mspace><mi>d</mi><mi>y</mi><mo>=</mo><msubsup><mo>∫</mo><mn>-3</mn><mn>3</mn></msubsup><mn>4</mn><msup><mi>y</mi><mn>2</mn></msup><mo stretchy="false">[</mo><mi>x</mi><msubsup><mo stretchy="false">]</mo><mn>-3</mn><mn>3</mn></msubsup><mspace width="0.167em"></mspace><mi>d</mi><mi>y</mi><mo>=</mo><mn>24</mn><msubsup><mo>∫</mo><mn>-3</mn><mn>3</mn></msubsup><msup><mi>y</mi><mn>2</mn></msup><mspace width="0.167em"></mspace><mi>d</mi><mi>y</mi><mo>=</mo><mn>24</mn><msubsup><mrow><mo>[</mo><mfrac><msup><mi>y</mi><mn>3</mn></msup><mn>3</mn></mfrac><mo>]</mo></mrow><mn>-3</mn><mn>3</mn></msubsup><mo>=</mo><mn>432</mn><mo>×</mo><msup><mn>10</mn><mn>-6</mn></msup><mspace width="0.167em"></mspace><mtext>C</mtext></mrow></math> fine.'
        container.prepend(p)
      }
    })

    // Apri lettura veloce
    await page.getByRole('button', { name: 'Lettura veloce', exact: true }).click()
    const reader = page.getByTestId('speed-reader')
    await expect(reader).toBeVisible()

    // Ogni formula apre una frase: la freccia destra salta di frase in frase.
    const word = page.getByTestId('speed-reader-word')
    await expect(word).toHaveAttribute('data-source-index', '0')
    await page.keyboard.press('ArrowRight')

    // 1. Formula corta: data-scale = 1
    await expect(word).toHaveAttribute('data-math', 'true')
    const shortScale = Number(await word.getAttribute('data-scale'))
    expect(shortScale).toBe(1)

    // Andiamo avanti fino alla formula lunga
    await page.keyboard.press('ArrowRight')

    // 2. Formula lunga: la scala si riduce per adattarsi
    await expect(word).toHaveAttribute('data-math', 'true')
    await expect.poll(async () => Number(await word.getAttribute('data-scale'))).toBeLessThan(1)

    // Verifica geometria: la formula sta dentro l'area di lettura ed è centrata
    const area = page.locator('.rt-rsvp-reading-area')
    const areaBox = await area.boundingBox()
    const formula = page.locator('.rt-rsvp-formula')
    const formulaBox = await formula.boundingBox()

    expect(areaBox).not.toBeNull()
    expect(formulaBox).not.toBeNull()

    // Dentro i limiti orizzontali dell'area di lettura (con tolleranza di 1 px)
    expect(formulaBox!.x).toBeGreaterThanOrEqual(areaBox!.x - 1)
    expect(formulaBox!.x + formulaBox!.width).toBeLessThanOrEqual(areaBox!.x + areaBox!.width + 1)

    // Centratura: differenza margini sinistro e destro entro 4 px
    const leftMargin = formulaBox!.x - areaBox!.x
    const rightMargin = (areaBox!.x + areaBox!.width) - (formulaBox!.x + formulaBox!.width)
    expect(Math.abs(leftMargin - rightMargin)).toBeLessThanOrEqual(4)

    // Chiudi lettura veloce per il prossimo ciclo del ciclo
    await page.keyboard.press('Escape')
    await expect(reader).not.toBeVisible()
  }
})
