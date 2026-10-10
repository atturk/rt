import { expect, type Page } from '@playwright/test'

import { test, apiGet, authHeaders, loginViaLink, openLessonDetails } from './support'

// Documento della lezione come in Obsidian (atomic-editor): si legge e si modifica nello stesso
// posto, senza modalità né avvisi, e si salva da solo nella bozza. CHIRURGIA è una lezione
// completa usata solo qui, perché il salvataggio rende il documento da ricreare.

type Lesson = { id: number; pending_issues: number }
type Section = { unit_id: string; start_seconds: number | null; start_formatted: string | null }
type LessonDocument = { markdown: string; sections: Section[] }

async function lesson(page: Page, materia: string) {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

const status = (page: Page) => page.getByTestId('editor-status')

test('documento modificabile in place: testo e timecode (triplo clic) salvati da soli, documento da ricreare', async ({ page }) => {
  await loginViaLink(page)
  const chir = await lesson(page, 'CHIRURGIA')
  const before = await apiGet<LessonDocument>(page.request, `/lessons/${chir.id}/document`)
  const oldTimecode = before.sections[0].start_formatted!
  await page.goto(`/lezioni/${chir.id}`)
  await openLessonDetails(page)
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'VALID')
  const doc = page.getByTestId('lesson-document')
  await expect(page.getByRole('button', { name: "Modifica l'anteprima" })).toHaveCount(0)

  // Il timecode è bloccato: scriverci accanto non lo cambia.
  const chip = doc.locator('.rt-timecode-locked', { hasText: oldTimecode }).first()
  await expect(chip).toBeVisible()
  await chip.click()
  await page.keyboard.type('99')
  await page.keyboard.press('Backspace')
  await expect(chip).toHaveText(oldTimecode)

  // Triplo clic: si sblocca e si seleziona. Un timecode fuori dall'audio: errore con la riga, niente salvataggio.
  await chip.click({ clickCount: 3 })
  await page.keyboard.type('59:00')
  const errors = page.getByTestId('document-edit-errors')
  await expect(errors).toContainText('Modifiche non compatibili con RT')
  await errors.getByRole('button', { name: 'Altre info' }).click()
  await expect(errors).toContainText('Riga')
  await expect(page.getByTestId('document-edit-help')).toContainText('Sezioni e unità non si aggiungono')

  // Timecode dentro l'audio e un paragrafo nuovo: si salva da solo.
  await doc.locator('.cm-line', { hasText: /^59:00$/ }).click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+End')
  await page.keyboard.type('01:00')
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.type('Paragrafo aggiunto a mano.')
  await expect(status(page)).toHaveAttribute('data-status', 'saved')
  await expect(page.getByTestId('document-edit-errors')).toHaveCount(0)

  // V5: dopo la ricarica testo salvato, timecode funzionante e documento aggiornato da solo.
  await page.reload()
  await expect(doc).toContainText('Paragrafo aggiunto a mano.')
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'VALID', { timeout: 30_000 })
  const after = await apiGet<LessonDocument>(page.request, `/lessons/${chir.id}/document`)
  const moved = after.sections[0]
  expect(moved.start_formatted).not.toBe(oldTimecode)
  expect(moved.start_seconds!).toBeLessThanOrEqual(60)
  const timecode = doc.locator('.rt-timecode').first()
  await expect(timecode).toHaveText(moved.start_formatted!)
  await page.locator('audio').evaluate((a: HTMLAudioElement) => (a.muted = true))
  await timecode.click()
  // L'audio di prova è più corto dei segmenti finti: il player si ferma alla fine.
  const duration = await page.locator('audio').evaluate((a: HTMLAudioElement) => a.duration)
  await expect
    .poll(() => page.locator('audio').evaluate((a: HTMLAudioElement) => a.currentTime))
    .toBeGreaterThanOrEqual(Math.min(moved.start_seconds!, duration) - 0.5)
})

test('anche con issue da valutare si modifica subito, senza avvisi; Ripristina toglie le modifiche non compatibili', async ({ page }) => {
  await loginViaLink(page)
  const farm = await lesson(page, 'FARMACOLOGIA')
  expect(farm.pending_issues).toBeGreaterThan(0)
  await page.goto(`/lezioni/${farm.id}`)
  const doc = page.getByTestId('lesson-document')
  const before = (await apiGet<LessonDocument>(page.request, `/lessons/${farm.id}/document`)).markdown
  await doc.locator('.cm-content').click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(doc.locator('.cm-content')).toBeFocused()

  // Una modifica che rompe la struttura (testo prima della prima sezione): non si salva, Ripristina la toglie.
  await page.keyboard.press('ControlOrMeta+Home')
  await page.keyboard.type('Testo fuori posto ')
  const errors = page.getByTestId('document-edit-errors')
  await expect(errors).toContainText('Modifiche non compatibili con RT')
  await errors.getByRole('button', { name: 'Ripristina', exact: true }).click()
  await expect(errors).toHaveCount(0)
  await expect(doc).not.toContainText('Testo fuori posto')
  expect((await apiGet<LessonDocument>(page.request, `/lessons/${farm.id}/document`)).markdown).toBe(before)
})


test('la barra si nasconde ma Ctrl/Cmd+B continua a formattare', async ({ page }) => {
  const prefs = await apiGet<Record<string, unknown>>(page.request, '/preferences')
  const names = ['editor.toolbar', 'editor.shortcuts']
  try {
    await page.request.put('/api/v1/preferences/editor.toolbar', { headers: authHeaders(), data: false })
    await page.request.put('/api/v1/preferences/editor.shortcuts', { headers: authHeaders(), data: {} })
    await loginViaLink(page)
    const l = await lesson(page, 'CHIRURGIA')
    await page.goto(`/lezioni/${l.id}`)
    await expect(page.getByRole('toolbar', { name: 'Strumenti dell’editor' })).toHaveCount(0)
    const doc = page.getByTestId('lesson-document')
    const before = (await apiGet<LessonDocument>(page.request, `/lessons/${l.id}/document`)).markdown
    const line = doc.locator('.cm-line').filter({ hasText: 'Paragrafo aggiunto a mano.' }).first()
    await line.click()
    await page.keyboard.press('Home')
    await page.keyboard.press('Shift+End')
    await page.keyboard.press('ControlOrMeta+b')
    await expect.poll(async () => (await apiGet<LessonDocument>(page.request, `/lessons/${l.id}/document`)).markdown).toContain('**Paragrafo aggiunto a mano.**')
    await page.keyboard.press('ControlOrMeta+z')
    await expect.poll(async () => (await apiGet<LessonDocument>(page.request, `/lessons/${l.id}/document`)).markdown).toBe(before)
  } finally {
    for (const name of names) {
      const response = prefs[name] === undefined
        ? await page.request.delete(`/api/v1/preferences/${name}`, { headers: authHeaders() })
        : await page.request.put(`/api/v1/preferences/${name}`, { headers: authHeaders(), data: prefs[name] })
      expect(response.ok()).toBeTruthy()
    }
  }
})
