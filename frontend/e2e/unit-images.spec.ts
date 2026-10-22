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
    const studyClip = page.getByRole('button', { name: 'Mostra le immagini', exact: true })
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
