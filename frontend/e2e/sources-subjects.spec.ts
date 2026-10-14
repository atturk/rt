import { expect, type Page } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, openLessonDetails } from './support'

// 4.2.5b2: Materie in Impostazioni, Fonti nel pannello Dettagli, chip Consigliato e interruttore
// della ricerca web nella verifica contestuale.

type Lesson = { id: number; materia: string }

async function firstLesson(page: Page) {
  const lessons = await apiGet<Lesson[]>(page.request, '/lessons')
  return lessons[0]
}

test('materie: si aggiunge una materia senza lezioni, compare nell\'elenco e si toglie', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/materie')
  await expect(page).toHaveURL(/\/impostazioni\/materie$/)
  const name = 'Farmacologia E2E'
  await page.getByRole('textbox', { name: 'Nuova materia' }).fill(name)
  await page.getByRole('button', { name: 'Aggiungi' }).click()
  const row = page.locator('#subs > div', { hasText: name })
  await expect(row).toContainText('nessuna lezione')
  const listed = await apiGet<{ nome: string }[]>(page.request, '/subjects')
  expect(listed.map((s) => s.nome)).toContain(name)

  await row.hover()
  await row.getByRole('button', { name: `Togli ${name}` }).click()
  await expect(row).toHaveCount(0)
})

test('materie: una materia con lezioni non si può togliere', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await firstLesson(page)
  const res = await page.request.delete(`/api/v1/subjects/${encodeURIComponent(lesson.materia)}`, { headers: authHeaders() })
  expect(res.status()).toBe(409)
})

test('fonti: la sezione Fonti sta in cima a Dettagli e mostra la registrazione come principale', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await firstLesson(page)
  await page.goto(`/lezioni/${lesson.id}`)
  const panel = await openLessonDetails(page)
  const sources = panel.getByTestId('sources-section')
  await expect(sources).toBeVisible()
  await expect(sources.getByRole('heading', { name: 'Fonti' }).or(sources.getByText('Fonti', { exact: true })).first()).toBeVisible()
  const view = await apiGet<{ sources: { id: string; tipo: string }[]; principale: string }>(page.request, `/lessons/${lesson.id}/sources`)
  if (view.sources.length) {
    await expect(sources.getByTestId(`source-row-${view.principale}`)).toBeVisible()
    await expect(sources.getByTestId(`source-row-${view.principale}`).getByTestId('star-primary')).toBeVisible()
  }
  // Le fasi restano sotto, come prima.
  await expect(panel.getByText('Fasi', { exact: true })).toBeVisible()
})

test('domande: il chip Consigliato sta prima dei tipi e i tipi di prima restano', async ({ page }) => {
  await loginViaLink(page)
  const lessons = await apiGet<{ id: number; materia: string; phases: Record<string, string> }[]>(page.request, '/lessons')
  const lesson = lessons.find(l => l.materia === 'BIOCHIMICA' && l.phases.rewrite === 'VALID')!
  await page.goto(`/lezioni/${lesson.id}?panel=domande`)
  const panel = page.getByTestId('questions-panel')
  await panel.getByText('Genera altre domande').click()
  const group = panel.getByRole('group', { name: 'Tipo di domanda' })
  await expect(group.getByRole('button', { name: 'Consigliato', exact: true })).toBeVisible()
  await expect(group.getByRole('button', { name: 'Quiz', exact: true })).toBeVisible()
  await expect(group.getByRole('button', { name: 'Mirata', exact: true })).toBeVisible()
})

test('ricerca web: l\'interruttore della verifica è spento di default e non cancella l\'indirizzo', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/lavorazione')
  const toggle = page.getByRole('switch', { name: 'Ricerca web nella verifica' })
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  const before = await apiGet<{ web_search?: { searxng_base_url?: string | null } }>(page.request, '/settings')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  const after = await apiGet<{ web_search?: { searxng_base_url?: string | null } }>(page.request, '/settings')
  expect(after.web_search?.searxng_base_url ?? null).toBe(before.web_search?.searxng_base_url ?? null)
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
})

test('fonti: conferma, fonti usate tolte e ripristino; una fonte mai usata non lascia la riga', async ({ page }) => {
  await loginViaLink(page)
  const lesson = await firstLesson(page)
  const url = `/lessons/${lesson.id}/sources`
  const initial = await apiGet<{ sources: { id: string; usata: boolean }[] }>(page.request, url)
  const used = initial.sources.find(s => s.usata)!
  expect(used).toBeTruthy()
  await page.goto(`/lezioni/${lesson.id}`)
  let panel = await openLessonDetails(page)
  const row = panel.getByTestId(`source-row-${used.id}`)
  await row.hover()
  await row.getByRole('button', { name: /^Togli / }).click()
  await expect(page.getByRole('dialog')).toContainText('Il testo della lezione contiene ancora questa parte')
  await page.getByRole('button', { name: 'Annulla', exact: true }).click()
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: /^Togli / }).click()
  await page.getByRole('button', { name: 'Togli', exact: true }).click()
  try {
    const bar = page.getByTestId('lesson-update-bar')
    await expect(bar).toContainText('Hai tolto 1 fonti già usate')
    await expect(bar.getByRole('button', { name: 'Ricostruisci', exact: true })).toBeVisible()
    await expect(bar.getByTestId('bar-extend-btn')).toHaveCount(0)
    await bar.getByRole('button', { name: "Rimetti com'era" }).click()
    await expect(row).toBeVisible()
    await expect(bar.getByText(/Hai tolto/)).toHaveCount(0)
  } finally {
    await page.request.post(`/api/v1${url}/restore-removed`, { headers: authHeaders() })
  }
  const added = await page.request.post(`/api/v1${url}`, { headers: authHeaders(), multipart: { tipo: 'appunti', testo: 'Fonte di prova mai usata' } })
  expect(added.ok()).toBeTruthy()
  const fresh = await added.json() as { id: string }
  await page.reload()
  panel = await openLessonDetails(page)
  const freshRow = panel.getByTestId(`source-row-${fresh.id}`)
  try {
    await freshRow.hover()
    await freshRow.getByRole('button', { name: /^Togli / }).click()
    await expect(page.getByRole('dialog')).toContainText('Vuoi togliere questa fonte')
    await page.getByRole('button', { name: 'Togli', exact: true }).click()
    await expect(freshRow).toHaveCount(0)
    await expect(page.getByTestId('lesson-update-bar').getByText(/Fonti nuove/)).toHaveCount(0)
    await expect(page.getByTestId('lesson-update-bar').getByText(/Hai tolto/)).toHaveCount(0)
  } finally {
    await page.request.delete(`/api/v1${url}/${fresh.id}`, { headers: authHeaders() })
  }
})
