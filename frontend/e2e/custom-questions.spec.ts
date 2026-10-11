import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink } from './support'

test('crea un tipo dai dati, classifica la lezione mock e genera una domanda', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<{ id: number; materia: string; phases: Record<string, string> }[]>(page.request, '/lessons')
  const lesson = lessons.find(l => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')!
  expect(lesson).toBeTruthy()
  await page.goto('/impostazioni/domande')
  await page.getByRole('button', { name: 'Nuovo tipo', exact: true }).click()
  await page.getByLabel('Nome', { exact: true }).fill('Applicazione didattica')
  await page.getByLabel('BIOCHIMICA', { exact: true }).check()
  await page.getByLabel('Cerca', { exact: true }).fill('Trova unità didattiche rielaborate.')
  await page.getByLabel('Chiedi', { exact: true }).fill('Chiedi di applicare il contenuto con risposta testuale.')
  await page.getByRole('button', { name: 'Salva tipo', exact: true }).click()
  await expect(page.getByTestId('question-type-applicazione-didattica')).toBeVisible()
  try {
    await page.goto(`/lezioni/${lesson.id}?panel=classificatore`)
    const row = page.getByTestId('classifier-job-custom:applicazione-didattica')
    await expect(row.getByRole('heading', { name: 'Applicazione didattica' })).toBeVisible()
    await row.getByRole('button', { name: 'Riclassifica tutte: Applicazione didattica', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Riclassifica', exact: true }).click()
    await expect(row.locator('[data-value=presente]').first()).toBeVisible({ timeout: 30_000 })
    await page.goto(`/lezioni/${lesson.id}?panel=domande`)
    const panel = page.getByTestId('questions-panel')
    await panel.getByText('Genera altre domande').click()
    await panel.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Applicazione didattica', exact: true }).click()
    await panel.getByRole('button', { name: 'Genera', exact: true }).click()
    await expect.poll(async () => {
      const data = await apiGet<{ questions: { custom_type?: string; type: string }[] }>(page.request, `/lessons/${lesson.id}/recall/history`)
      return data.questions.some(q => q.type === 'personalizzata' && q.custom_type === 'applicazione-didattica')
    }, { timeout: 30_000 }).toBe(true)
    await expect(panel.getByText('Applicazione didattica', { exact: true }).first()).toBeVisible()
  } finally {
    const response = await page.request.delete('/api/v1/settings/questions/applicazione-didattica', { headers: authHeaders() })
    expect(response.ok()).toBeTruthy()
  }
})
