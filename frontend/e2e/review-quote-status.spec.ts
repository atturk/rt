import { expect } from '@playwright/test'
import { test, apiGet, loginViaLink, scrollDocumentTo } from './support'

test('salvare un passaggio cambiato ricarica lo stato server nella card della verifica', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=FARMACOLOGIA')
  type Item = { issue: { id: string; claim: string }; decision: unknown; fix_text: string | null; quote_status: string | null }
  const items = await apiGet<{ items: Item[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)
  const item = items.items.find(item => !item.decision && item.fix_text && item.quote_status === 'found' && item.issue.claim.length > 8 && !item.issue.claim.includes('\n'))!
  expect(item).toBeTruthy()
  await page.goto(`/lezioni/${lesson.id}?panel=verifica&issue=${item.issue.id}`)
  const line = page.getByTestId('lesson-document').locator('.cm-line').filter({ hasText: item.issue.claim }).first()
  await scrollDocumentTo(page, line)
  await line.click()
  const selected = await line.evaluate(element => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    return selection.toString()
  })
  expect(selected).toContain(item.issue.claim)
  await page.keyboard.type('Passaggio riscritto a mano nell’editor.')
  await expect(page.getByTestId('editor-status')).toHaveAttribute('data-status', 'saved')
  await expect.poll(async () => (await apiGet<{ items: Item[] }>(page.request, `/lessons/${lesson.id}/issues?status=all`)).items.find(row => row.issue.id === item.issue.id)?.quote_status).toBe('changed')
  const card = page.getByTestId('lesson-review-panel').getByTestId('issue-detail')
  await expect(card).toContainText('Testo cambiato')
  await expect(card.getByRole('button', { name: 'Chiudi', exact: true })).toBeEnabled()
  await expect(card.getByRole('button', { name: "Verifica di nuovo l'unità" })).toBeEnabled()
  await expect(card.getByRole('button', { name: 'Accetta la correzione' })).toHaveCount(0)
})
