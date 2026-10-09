import { fileURLToPath } from 'node:url'
import { expect, type Page } from '@playwright/test'

import { test, apiGet, disableOutlineTimer, loginViaLink, openLessonDetails, scrollDocumentTo, tinyPdf } from './support'

// RT4-F7 (aggiornato in FA9): il percorso completo di una lezione nuova solo dalla SPA, come
// 'rt run' da terminale: accesso con il link, Nuova lezione, scaletta nella pagina della lezione,
// verifica di tutte le issue nel pannello, documento, ripasso, immagini dal pannello Arricchimento e
// documento ricreato come conferma finale (FA2), modifica delle impostazioni. Dopo ogni passo la pagina si ricarica e quello che
// mostra deve venire dal backend.

const AUDIO = fileURLToPath(new URL('../../tests/fixtures/demo_lecture.wav', import.meta.url))
const LONG = 90_000

type Job = { id: string; state: string; lesson_id: number | null; decision: { kind: string } | null }
type Lesson = { id: number; materia: string; pending_issues: number; phases: Record<string, string> }
type Outline = { approved: boolean }
type IssueList = { total: number }
type Decision = { issue_id: string; decision: string }
type Settings = { transcription: { engine: string; base_url: string | null; model: string | null } }
type History = { questions: { id: string; status: string }[]; answers: { question_id: string }[] }

async function job(page: Page, id: string) {
  return apiGet<Job>(page.request, `/jobs/${id}`)
}

async function waitJob(page: Page, id: string, check: (j: Job) => boolean) {
  await expect.poll(async () => check(await job(page, id)), { timeout: LONG, intervals: [500] }).toBe(true)
}

test('percorso completo: dall\'audio al documento con le immagini, con ricarica dopo ogni passo', async ({ page }) => {
  test.setTimeout(10 * LONG)

  // 1. Accesso con il link monouso: la sessione resta dopo la ricarica.
  await loginViaLink(page)
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Lezioni' })).toBeAttached()

  // 2. Nuova lezione dal popup con la revisione, che si ferma sulla scaletta.
  await disableOutlineTimer(page.request)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('button', { name: 'Nuova lezione' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuova lezione' })
  await dialog.getByLabel('Audio o pacchetto della lezione').setInputFiles(AUDIO)
  await dialog.getByLabel(/^Data/).fill('2026-09-25')
  await dialog.getByLabel('Materia').fill('EMBRIOLOGIA')
  const review = dialog.getByRole('button', { name: 'Revisione' })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await dialog.getByRole('button', { name: 'Avvia' }).click()
  await expect(page).toHaveURL(/\/lezioni\/\d+$/, { timeout: LONG })
  const lessonId = Number(page.url().split('/lezioni/')[1])
  expect((await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)).materia).toBe('EMBRIOLOGIA')
  const jobId = (await apiGet<Job[]>(page.request, `/jobs?lesson_id=${lessonId}`))[0].id
  await waitJob(page, jobId, (j) => j.decision?.kind === 'outline_approval')

  // 3. Approvazione della scaletta nella pagina della lezione.
  await page.reload()
  await page.getByTestId('outline-approval').getByRole('button', { name: /^Approva/ }).click()
  await expect.poll(async () => (await apiGet<Outline>(page.request, `/lessons/${lessonId}/outline`)).approved).toBe(true)
  await page.reload()
  await expect(page.getByTestId('outline-approval')).toHaveCount(0)

  // 4. Verifica di tutte le issue nel pannello: la pipeline riparte da sola e arriva al build.
  await waitJob(page, jobId, (j) => j.decision?.kind === 'science_issue')
  let { total } = await apiGet<IssueList>(page.request, `/lessons/${lessonId}/issues?status=all`)
  expect(total).toBeGreaterThan(0)
  await page.goto(`/lezioni/${lessonId}`)
  await page.getByTestId('lesson-waiting').getByRole('link', { name: 'Vai alla decisione' }).click()
  const panel = page.getByTestId('lesson-review-panel')
  const counter = panel.getByRole('status').first()
  const acceptPending = async (pending: number) => {
    await expect(counter).toHaveText(`${pending} da decidere su ${total}`)
    for (let left = pending - 1; left >= 0; left--) {
      await panel.getByTestId('issue-detail').getByRole('button', { name: 'Accetta' }).click()
      await expect(counter).toHaveText(left ? `${left} da decidere su ${total}` : 'Tutte decise')
    }
  }
  await acceptPending(total)
  // V1: alla ripresa la verifica legge le correzioni approvate. Il critic mock
  // produce un secondo gruppo su quel testo; le decisioni del primo restano.
  await expect.poll(async () => (await apiGet<IssueList>(page.request,
    `/lessons/${lessonId}/issues?status=all`)).total, { timeout: LONG }).toBeGreaterThan(total)
  const previousTotal = total
  total = (await apiGet<IssueList>(page.request, `/lessons/${lessonId}/issues?status=all`)).total
  await page.reload()
  await acceptPending(total - previousTotal)
  await waitJob(page, jobId, (j) => j.state === 'succeeded')
  await page.reload()
  await expect(counter).toHaveText('Tutte decise')
  const decisions = await apiGet<Decision[]>(page.request, `/lessons/${lessonId}/decisions`)
  expect(decisions.map((d) => d.decision)).toEqual(Array(total).fill('accepted'))

  // 5. Documento finale con l'audio: build valido, unità con timecode, player.
  await page.goto(`/lezioni/${lessonId}`)
  await page.reload()
  await openLessonDetails(page)
  await expect(page.locator('[data-phase-row="build"]')).toHaveAttribute('data-status', 'VALID')
  expect((await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)).phases.build).toBe('VALID')
  await expect(page.getByTestId('lesson-document').locator('[data-unit-id]').first()).toBeVisible()
  await expect(page.locator('audio')).toHaveCount(1)

  // 6. Ripasso sulla lezione nuova: domande dal pannello Domande, un quiz, risposta salvata.
  await page.goto(`/lezioni/${lessonId}?panel=domande`)
  const questions = page.getByTestId('questions-panel')
  await questions.getByText('Genera altre domande').click()
  await questions.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Quiz', exact: true }).click()
  await questions.getByRole('button', { name: 'Genera', exact: true }).click()
  await expect.poll(async () => (await apiGet<History>(page.request, `/lessons/${lessonId}/recall/history`)).questions.length, { timeout: LONG }).toBeGreaterThan(0)
  await page.reload()
  await page.getByTestId('questions-panel').getByRole('link', { name: 'Ripassa' }).click()
  await page.getByRole('group', { name: 'Tipo di domanda' }).getByRole('button', { name: 'Quiz', exact: true }).click()
  await expect(page.getByTestId('recall-question')).toHaveAttribute('data-type', 'quiz')
  await page.getByRole('button', { name: /^A\./ }).click()
  await expect(page.getByTestId('recall-result-card')).toBeVisible()
  const askedId = (await page.getByTestId('recall-question').getAttribute('data-question-id'))!
  const history = await apiGet<History>(page.request, `/lessons/${lessonId}/recall/history`)
  const answered = history.questions.find((q) => q.id === askedId)!
  expect(answered.status).toBe('answered')
  expect(history.answers.some((a) => a.question_id === answered.id)).toBe(true)

  // 7. Immagini dopo il documento: entrano nell'anteprima e il documento diventa da ricreare.
  await page.goto(`/lezioni/${lessonId}?panel=arricchimento`)
  const enrichment = page.getByTestId('enrichment-panel')
  await enrichment.getByRole('button', { name: 'Aggiungi immagini (PDF o foto)' }).click()
  await enrichment.getByLabel('PDF o foto', { exact: true }).setInputFiles({ name: 'slide.pdf', mimeType: 'application/pdf', buffer: tinyPdf() })
  await enrichment.getByRole('button', { name: /^Carica/ }).click()
  await expect.poll(async () => (await apiGet<{ images: unknown[] }>(page.request, `/lessons/${lessonId}/images`)).images.length, { timeout: LONG }).toBeGreaterThan(0)
  await expect.poll(async () => (await apiGet<{ state: string }[]>(page.request, `/jobs?lesson_id=${lessonId}`)).some((j) => ['queued', 'running'].includes(j.state)), { timeout: 60_000 }).toBe(false)
  const images = (await apiGet<{ images: { url: string; in_document: boolean }[] }>(page.request, `/lessons/${lessonId}/images`)).images
  const placed = images.filter((i) => i.in_document)
  expect(placed.length).toBeGreaterThan(0)
  expect((await apiGet<Lesson>(page.request, `/lessons/${lessonId}`)).phases.build).toBe('STALE')

  // 8. Documento come conferma finale: Esegui Documento (con il dialogo, se ci sono avvisi) e
  //    documento aggiornato con le immagini dopo la ricarica.
  await page.goto(`/lezioni/${lessonId}`)
  await openLessonDetails(page)
  const build = page.locator('[data-phase-row="build"]')
  await expect(build).toHaveAttribute('data-status', 'STALE')
  await page.getByTestId('details-panel').getByRole('button', { name: 'Ricrea' }).click()
  const confirm = page.getByRole('dialog', { name: 'Creare il documento finale?' })
  if (await confirm.isVisible()) await confirm.getByRole('button', { name: 'Crea il documento comunque' }).click()
  await expect(build).toHaveAttribute('data-status', 'VALID', { timeout: LONG })
  await page.reload()
  await expect(build).toHaveAttribute('data-status', 'VALID')
  expect((await apiGet<{ final: boolean }>(page.request, `/lessons/${lessonId}/document`)).final).toBe(true)
  const placedImage = page.getByTestId('lesson-document').locator(`img[src="${placed[0].url}"]`)
  await scrollDocumentTo(page, placedImage)
  await expect(placedImage).toBeVisible()

  // 9. Impostazioni: il motore di trascrizione cambiato resta dopo la ricarica (poi si ripristina).
  await page.goto('/impostazioni/lavorazione')
  const card = page.getByRole('region', { name: 'Trascrizione', exact: true })
  const engine = card.getByTestId('stt-engine')
  const before = (await apiGet<Settings>(page.request, '/settings')).transcription
  const chooseEngine = async (option: string) => {
    await card.getByRole('button', { name: 'Motore', exact: true }).click()
    await page.getByRole('menuitemradio', { name: option, exact: true }).click()
  }
  const beforeLabel = (await engine.locator('span').first().textContent())!
  await chooseEngine('Server OpenAI-compatible')
  await card.getByLabel('Base URL del server').fill('http://127.0.0.1:9100/v1')
  await card.getByLabel('Modello', { exact: true }).fill('whisper-percorso')
  await card.getByRole('button', { name: 'Salva trascrizione' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()
  await page.reload()
  await expect(engine).toHaveAttribute('data-value', 'custom')
  await expect(card.getByLabel('Modello', { exact: true })).toHaveValue('whisper-percorso')
  expect((await apiGet<Settings>(page.request, '/settings')).transcription).toMatchObject({
    engine: 'custom', base_url: 'http://127.0.0.1:9100/v1', model: 'whisper-percorso',
  })
  if (before.engine !== 'custom') await chooseEngine(beforeLabel)
  await card.getByRole('button', { name: 'Salva trascrizione' }).click()
  await page.reload()
  await expect(engine).toHaveAttribute('data-value', before.engine)
})
