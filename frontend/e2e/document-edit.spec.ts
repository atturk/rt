import { expect, test, type Page } from '@playwright/test'

import { apiGet, loginViaLink, openLessonDetails } from './support'

// RT4-FA3: modifica dell'anteprima (beta). CHIRURGIA è una lezione completa usata solo qui,
// perché il salvataggio rende il documento da ricreare. Gli avvisi "Non mostrare più" sono
// impostazioni del server: restano per i test successivi.

type Lesson = { id: number; pending_issues: number }
type Section = { unit_id: string; start_seconds: number | null; start_formatted: string | null }
type LessonDocument = { markdown: string; sections: Section[] }
type Settings = { notices: { dismissed: string[] } }

async function lesson(page: Page, materia: string) {
  const [l] = await apiGet<Lesson[]>(page.request, `/lessons?materia=${materia}`)
  return l
}

function editor(page: Page) {
  return page.getByTestId('markdown-editor')
}

test("modifica dell'anteprima: testo e timecode salvati, documento da ricreare, avvisi da non mostrare più", async ({ page }) => {
  await loginViaLink(page)
  const pencil = page.getByRole('button', { name: "Modifica l'anteprima" })
  const notice = page.getByRole('dialog', { name: "Modifica dell'anteprima" })

  // Lezione con issue da valutare: i due avvisi; Annulla non entra in modifica.
  const farm = await lesson(page, 'FARMACOLOGIA')
  expect(farm.pending_issues).toBeGreaterThan(0)
  await page.goto(`/lezioni/${farm.id}`)
  await pencil.click()
  await expect(notice.locator('[data-notice=preview_edit_issues]')).toBeVisible()
  await expect(notice.locator('[data-notice=preview_edit_beta]')).toBeVisible()
  await notice.getByRole('button', { name: 'Annulla' }).click()
  await expect(notice).toBeHidden()
  await expect(editor(page)).toHaveCount(0)

  // Lezione senza issue: solo l'avviso beta, che non si mostrerà più.
  const chir = await lesson(page, 'CHIRURGIA')
  const before = await apiGet<LessonDocument>(page.request, `/lessons/${chir.id}/document`)
  const oldTimecode = before.sections[0].start_formatted!
  await page.goto(`/lezioni/${chir.id}`)
  await openLessonDetails(page)
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'VALID')
  await pencil.click()
  await expect(notice.locator('[data-notice=preview_edit_issues]')).toHaveCount(0)
  await notice.locator('[data-notice=preview_edit_beta]').getByLabel('Non mostrare più').check()
  await notice.getByRole('button', { name: 'Modifica' }).click()
  await expect(editor(page)).toBeVisible()
  await expect
    .poll(async () => (await apiGet<Settings>(page.request, '/settings')).notices.dismissed)
    .toContain('preview_edit_beta')

  // Un timecode fuori dall'audio: errore con la riga, niente salvataggio.
  const timecodeLine = editor(page).locator('.cm-line', { hasText: new RegExp(`^${oldTimecode}$`) })
  await timecodeLine.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+End')
  await page.keyboard.type('59:00')
  await expect(page.getByTestId('document-edit-errors')).toContainText('Riga')

  // Timecode dentro l'audio e un paragrafo nuovo.
  const edited = editor(page).locator('.cm-line', { hasText: /^59:00$/ })
  await edited.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+End')
  await page.keyboard.type('01:00')
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.type('Paragrafo aggiunto a mano.')
  await expect(page.getByTestId('document-edit-errors')).toHaveCount(0)
  await expect(editor(page)).toContainText('Paragrafo aggiunto a mano.')
  await page.getByRole('button', { name: 'Fine' }).click()
  await expect(editor(page)).toHaveCount(0)
  await expect(page.getByTestId('document-edit-saved')).toContainText('va ricreato')

  // Dopo la ricarica: testo salvato, timecode spostato e funzionante, documento da ricreare.
  await page.reload()
  const doc = page.getByTestId('lesson-document')
  await expect(doc).toContainText('Paragrafo aggiunto a mano.')
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'STALE')
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

  // L'avviso beta non torna; Esc annulla senza salvare.
  await pencil.click()
  await expect(notice).toBeHidden()
  await expect(editor(page)).toBeVisible()
  await page.keyboard.type('testo da buttare ')
  await page.keyboard.press('Escape')
  await expect(editor(page)).toHaveCount(0)
  await expect(doc).not.toContainText('testo da buttare')
  expect((await apiGet<LessonDocument>(page.request, `/lessons/${chir.id}/document`)).markdown).toBe(after.markdown)

  // Sull'altra lezione resta solo l'avviso delle issue.
  await page.goto(`/lezioni/${farm.id}`)
  await pencil.click()
  await expect(notice.locator('[data-notice=preview_edit_beta]')).toHaveCount(0)
  await expect(notice.locator('[data-notice=preview_edit_issues]')).toBeVisible()
  await notice.getByRole('button', { name: 'Annulla' }).click()
})
