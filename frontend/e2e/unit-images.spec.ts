import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

test('graffetta: immagine dal testo alla sezione, persistenza e Studio', async ({ page }) => {
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=CHIRURGIA')
  const before = await apiGet<{ markdown: string; sections: { unit_id: string }[] }>(page.request, `/lessons/${lesson.id}/document`)
  const response = await page.request.post(`/api/v1/lessons/${lesson.id}/media/images`, {
    headers: authHeaders(), multipart: { file: { name: 'figura.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAKAAAABkCAIAAACO1KzYAAABAklEQVR4nO3RAQkAIQDAwPdjGMwsxjeFCOMuwWBj7vXR9b8O4C6D4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOMzjO4DiD4wyOO3PUAbDMRfCMAAAAAElFTkSuQmCC', 'base64') } },
  })
  expect(response.ok()).toBeTruthy()
  const image = await response.json() as { name: string; path: string; alt_text: string }
  try {
    await loginViaLink(page)
    await page.goto(`/lezioni/${lesson.id}`)
    const editor = page.getByTestId('lesson-document')
    await editor.locator('.cm-content').click()
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+ArrowDown' : 'ControlOrMeta+End')
    await page.evaluate(item => window.dispatchEvent(new CustomEvent('rt-editor-insert-images', { detail: { items: [item] } })), image)
    await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain(`${image.name}#w=`)
    const target = editor.locator(`.rt-unit-images-button[data-unit-images="${before.sections[0].unit_id}"]`)
    // Il trascinamento fa comparire anche il bersaglio della sezione vuota.
    await editor.locator('.cm-content').dispatchEvent('dragover', { dataTransfer: await page.evaluateHandle(() => {
      const transfer = new DataTransfer(); transfer.setData('application/x-rt-section-image', ''); return transfer
    }) })
    await expect(target).toBeVisible()
    const inline = editor.locator(`img[data-image-name="${image.name}"]`)
    const transfer = await page.evaluateHandle(() => new DataTransfer())
    await inline.dispatchEvent('dragstart', { dataTransfer: transfer })
    await target.dispatchEvent('drop', { dataTransfer: transfer })
    await target.dispatchEvent('dragend')
    await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).not.toContain(`${image.name}#w=`)
    await expect(target).toHaveText('1')
    await target.click()
    await expect(editor.locator('.rt-unit-images-section .thumb')).toHaveCount(1)
    await page.reload()
    const clip = editor.getByRole('button', { name: 'Mostra le immagini', exact: true })
    await expect(clip).toHaveText('1')
    await clip.click()
    await expect(editor.locator('.rt-unit-images-section .thumb')).toBeVisible()
    await page.goto(`/studio/lezione/${lesson.id}?unita=${before.sections[0].unit_id}`)
    const studyClip = page.getByRole('button', { name: 'Mostra le immagini · M' })
    await expect(studyClip).toHaveText('1')
    await studyClip.click()
    await expect(page.locator('.rt-unit-images-section .thumb')).toBeVisible()
  } finally {
    await page.goto('about:blank')
    await expect.poll(async () => (await page.request.put(`/api/v1/lessons/${lesson.id}/document/draft`, {
      headers: authHeaders(), data: { markdown: before.markdown },
    })).status()).toBe(200)
  }
})

test('anteprima modificabile: clic apre il visore, doppio clic mostra il markdown sorgente', async ({ page }) => {
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=ANATOMIA')
  const before = await apiGet<{ markdown: string; sections: { unit_id: string }[] }>(page.request, `/lessons/${lesson.id}/document`)
  const response = await page.request.post(`/api/v1/lessons/${lesson.id}/media/images`, {
    headers: authHeaders(), multipart: { file: { name: 'figura-gesti.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64') } },
  })
  expect(response.ok()).toBeTruthy()
  const image = await response.json() as { name: string; path: string; alt_text: string }
  try {
    await loginViaLink(page)
    await page.goto(`/lezioni/${lesson.id}`)
    const editor = page.getByTestId('lesson-document')
    await editor.locator('.cm-content').click()
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+ArrowDown' : 'ControlOrMeta+End')
    await page.evaluate(item => window.dispatchEvent(new CustomEvent('rt-editor-insert-images', { detail: { items: [item] } })), image)
    await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain(`${image.name}#w=`)

    const inline = editor.locator(`img[data-image-name="${image.name}"]`)
    await expect(inline).toBeVisible()

    // 1. Clic singolo a pannello chiuso: apre il visore
    await inline.click()
    const viewer = page.getByRole('dialog', { name: 'Visore immagini' })
    await expect(viewer).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(viewer).not.toBeVisible()

    // 2. Doppio clic sull'immagine: mostra il testo markdown sorgente ![]
    await inline.dblclick()
    await expect(editor.locator('.cm-content')).toContainText(`![${image.alt_text || 'figura-gesti'}`)
    await expect(viewer).not.toBeVisible()
  } finally {
    await page.goto('about:blank')
    await expect.poll(async () => (await page.request.put(`/api/v1/lessons/${lesson.id}/document/draft`, {
      headers: authHeaders(), data: { markdown: before.markdown },
    })).status()).toBe(200)
  }
})

test('trascinamento reale dal pannello Arricchimento al testo: il rilascio inserisce l’immagine', async ({ page }) => {
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=CHIRURGIA')
  const before = await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)
  const response = await page.request.post(`/api/v1/lessons/${lesson.id}/media/images`, {
    headers: authHeaders(), multipart: { file: { name: 'figura-drop.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64') } },
  })
  expect(response.ok()).toBeTruthy()
  const image = await response.json() as { name: string }
  try {
    await page.setViewportSize({ width: 1400, height: 900 })
    await loginViaLink(page)
    await page.goto(`/lezioni/${lesson.id}`)
    await page.getByTestId('lesson-actions').getByRole('button', { name: 'Arricchimento' }).click()
    const cell = page.getByTestId(`media-cell-${image.name}`)
    await expect(cell).toBeVisible()
    const text = page.getByTestId('lesson-document').locator('.cm-line').filter({ hasText: 'Correzione #3' })
    const from = (await cell.boundingBox())!
    const to = (await text.boundingBox())!
    // Mouse vero: dragstart nativo, l'anteprima segue il cursore e il testo deve accettare il rilascio.
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(from.x - 40, from.y + 20, { steps: 5 })
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 10 })
    await expect(page.locator('.rt-drag-preview')).toBeVisible()
    await expect(page.getByTestId('drag-preview-ban')).toHaveCount(0)
    // L'editor deve ricevere il dragover (in WebKit senza di esso il rilascio è rifiutato): compare la linea di rilascio.
    await expect(page.locator('.cm-drop-line-widget')).toBeAttached()
    await page.mouse.up()
    await expect(page.locator('.rt-drag-preview')).toHaveCount(0)
    await expect.poll(async () => (await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)).markdown).toContain(image.name)
  } finally {
    await page.goto('about:blank')
    await expect.poll(async () => (await page.request.put(`/api/v1/lessons/${lesson.id}/document/draft`, {
      headers: authHeaders(), data: { markdown: before.markdown },
    })).status()).toBe(200)
  }
})
