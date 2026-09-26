import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink, serverState } from './support'

// RT4-F5: ogni campo si scrive dalla pagina, si ricarica e si rilegge sia dalla pagina sia
// dall'API. Nessuna risposta né pagina contiene il valore di una chiave.

type Phase = { job: string; label: string; connection: string | null; model: string | null }
type Settings = {
  lessons_root: string | null
  data_dir: string | null
  setup_required: boolean
  transcription: { engine: string; base_url: string | null; model: string | null; api_key_set: boolean }
  telegram: { bot_token_set: boolean; chat_id: string | null; topics: Record<string, number>; misc_topic_id: number | null }
  phases: Phase[]
  connections: { name: string; provider: string; base_url: string; models: string[]; credentials: { name: string; set: boolean }[] }[]
  credentials: { name: string; provider: string; env_var: string; set: boolean }[]
  pricing: Record<string, Record<string, Record<string, number>>>
}

const settings = (page: Page) => apiGet<Settings>(page.request, '/settings')

// Connessione verso una porta chiusa: la prova della chiave fallisce subito e senza rete.
const CONNECTION = 'Server locale'
const BASE_URL = 'http://127.0.0.1:9/v1'
const KEY_1 = 'sk-e2e-prima-chiave-0123456789abcdef'
const KEY_2 = 'sk-e2e-seconda-chiave-fedcba9876543210'
const BOT_TOKEN = '123456789:AAE2E-token-del-bot-di-prova-xyz'
const STT_KEY = 'stt-e2e-chiave-trascrizione-4242'
const SECRETS = [KEY_1, KEY_2, BOT_TOKEN, STT_KEY]
const JOBS = ['outline', 'rewrite', 'review', 'recall', 'image_description', 'image_unit_judge']

async function expectNoSecretIn(page: Page) {
  const html = await page.content()
  for (const secret of SECRETS) expect(html).not.toContain(secret)
}

async function section(page: Page, title: string) {
  return page.getByRole('region', { name: title, exact: true })
}

test.describe.configure({ mode: 'serial' })

test('cartella dati: scrivi, ricarica, rileggi (e ripristina)', async ({ page }) => {
  const original = serverState().lessons_root
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Navigazione' }).getByRole('link', { name: 'Impostazioni' }).click()
  await expect(page).toHaveURL(/\/impostazioni$/)
  const card = await section(page, 'Cartella dati')
  await expect(card.getByLabel('Cartella delle lezioni')).toHaveValue(original)
  await expect(card.getByTestId('data-dir')).toHaveText((await settings(page)).data_dir!)

  const other = `${original}-altra`
  await card.getByLabel('Cartella delle lezioni').fill(other)
  await card.getByRole('button', { name: 'Salva' }).click()
  await expect(card.getByRole('status')).toHaveText('Salvato.')
  await page.reload()
  await expect(card.getByLabel('Cartella delle lezioni')).toHaveValue(other)
  expect((await settings(page)).lessons_root).toBe(other)

  await card.getByLabel('Cartella delle lezioni').fill(original)
  await card.getByRole('button', { name: 'Salva' }).click()
  await expect(card.getByRole('status')).toHaveText('Salvato.')
  await page.reload()
  await expect(card.getByLabel('Cartella delle lezioni')).toHaveValue(original)
  expect((await settings(page)).lessons_root).toBe(original)
})

test('trascrizione: motore, server, modello e chiave', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const card = await section(page, 'Trascrizione')
  await expect(card.getByText('Mancante')).toBeVisible()
  await card.getByLabel('Motore').selectOption('custom')
  await card.getByLabel('Base URL del server').fill('http://127.0.0.1:9000/v1')
  await card.getByLabel('Modello').fill('whisper-e2e')
  await card.getByLabel('Chiave API (facoltativa)').fill(STT_KEY)
  await card.getByRole('button', { name: 'Salva trascrizione' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()

  await page.reload()
  await expect(card.getByLabel('Motore')).toHaveValue('custom')
  await expect(card.getByLabel('Base URL del server')).toHaveValue('http://127.0.0.1:9000/v1')
  await expect(card.getByLabel('Modello')).toHaveValue('whisper-e2e')
  await expect(card.getByLabel('Chiave API (facoltativa)')).toHaveValue('')
  await expect(card.getByText('Impostata')).toBeVisible()
  expect((await settings(page)).transcription).toEqual({
    engine: 'custom',
    base_url: 'http://127.0.0.1:9000/v1',
    model: 'whisper-e2e',
    api_key_set: true,
  })
  await expectNoSecretIn(page)

  // Torna a macparakeet: la chiave salvata resta.
  await card.getByLabel('Motore').selectOption('macparakeet')
  await card.getByRole('button', { name: 'Salva trascrizione' }).click()
  await page.reload()
  await expect(card.getByLabel('Motore')).toHaveValue('macparakeet')
  expect((await settings(page)).transcription.engine).toBe('macparakeet')
})

test('Telegram: token, chat, topic per materia dal link, topic generale', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const card = await section(page, 'Telegram')
  await card.getByLabel('Token del bot').fill(BOT_TOKEN)
  await card.getByLabel('Link a un messaggio del topic').fill('https://t.me/c/1234567890/12/34')
  await card.getByRole('button', { name: 'Aggiungi dal link' }).click()
  await expect(card.getByLabel('Chat ID del gruppo')).toHaveValue('-1001234567890')
  const rows = card.getByTestId('topic-row')
  await expect(rows).toHaveCount(1)
  await expect(card.getByLabel('Topic 1', { exact: true })).toHaveValue('12')
  await card.getByLabel('Materia 1', { exact: true }).fill('biochimica')
  await card.getByRole('button', { name: 'Aggiungi topic' }).click()
  await card.getByLabel('Materia 2', { exact: true }).fill('FISIOLOGIA')
  await card.getByLabel('Topic 2', { exact: true }).fill('27')
  await card.getByLabel('Topic generale (facoltativo)').fill('3')
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()

  await page.reload()
  await expect(card.getByLabel('Chat ID del gruppo')).toHaveValue('-1001234567890')
  await expect(rows).toHaveCount(2)
  await expect(card.getByLabel('Materia 1', { exact: true })).toHaveValue('BIOCHIMICA')
  await expect(card.getByLabel('Topic 1', { exact: true })).toHaveValue('12')
  await expect(card.getByLabel('Materia 2', { exact: true })).toHaveValue('FISIOLOGIA')
  await expect(card.getByLabel('Topic 2', { exact: true })).toHaveValue('27')
  await expect(card.getByLabel('Topic generale (facoltativo)')).toHaveValue('3')
  // Il pannello del bot (RT4-F6) sta anche nelle impostazioni.
  await expect(page.getByTestId('telegram-bot')).toBeVisible()
  await expect(card.getByLabel('Token del bot')).toHaveValue('')
  await expect(card.getByText('Impostata')).toBeVisible()
  const tg = (await settings(page)).telegram
  expect(tg).toMatchObject({ bot_token_set: true, chat_id: '-1001234567890', topics: { BIOCHIMICA: 12, FISIOLOGIA: 27 }, misc_topic_id: 3 })
  await expectNoSecretIn(page)

  // Un topic tolto sparisce anche dal backend.
  await card.getByRole('button', { name: 'Rimuovi topic 2' }).click()
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await page.reload()
  await expect(rows).toHaveCount(1)
  expect((await settings(page)).telegram.topics).toEqual({ BIOCHIMICA: 12 })

  // "Ascolta i topic": job del worker contro la Bot API finta del server e2e (topic 12 e 27).
  await card.getByRole('button', { name: 'Ascolta i topic per 20 secondi' }).click()
  await expect(card.getByTestId('listen-result')).toHaveText('Rilevati 2 topic. Assegna una materia a ciascuno e salva.', { timeout: 30_000 })
  await expect(rows).toHaveCount(2)
  await expect(card.getByLabel('Topic 2', { exact: true })).toHaveValue('27')
  await card.getByLabel('Materia 2', { exact: true }).fill('FISIOLOGIA')
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await page.reload()
  await expect(rows).toHaveCount(2)
  expect((await settings(page)).telegram.topics).toEqual({ BIOCHIMICA: 12, FISIOLOGIA: 27 })
  await expectNoSecretIn(page)
})

test('connessione nuova e un modello per ciascuna delle sei fasi', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/modelli')
  const form = page.getByRole('form', { name: 'Nuova connessione' })
  await form.getByLabel('Nome connessione').fill(CONNECTION)
  await form.getByLabel('Provider').selectOption('openai_compatible')
  await form.getByLabel('Base URL').fill(BASE_URL)
  await form.getByLabel('Chiave API 1').fill(KEY_1)
  await form.getByRole('button', { name: 'Aggiungi chiave' }).click()
  await form.getByLabel('Chiave API 2').fill(KEY_2)
  await form.getByRole('button', { name: 'Crea connessione' }).click()
  await expect(form.getByRole('status')).toHaveText('Connessione creata.')

  await page.reload()
  const conn = page.getByRole('group', { name: `Connessione ${CONNECTION}` })
  await expect(conn).toContainText(BASE_URL)
  await expect(conn.getByText('Impostata')).toHaveCount(2)
  await conn.getByLabel(`Nuovo modello per ${CONNECTION}`).fill('modello/extra')
  await conn.getByRole('button', { name: 'Aggiungi' }).click()
  await expect(conn.getByTestId('connection-models')).toContainText('modello/extra')
  await page.reload()
  await expect(conn.getByTestId('connection-models')).toContainText('modello/extra')

  for (const job of JOBS) {
    const row = page.locator(`[data-testid=phase-row][data-job="${job}"]`)
    await row.locator(`#fase-${job}-connessione`).selectOption(CONNECTION)
    await row.locator(`#fase-${job}-modello`).fill(`modello/${job}`)
    await row.getByRole('button', { name: 'Salva' }).click()
    await expect(row.getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/${job}`)
  }

  await page.reload()
  for (const job of JOBS) {
    const row = page.locator(`[data-testid=phase-row][data-job="${job}"]`)
    await expect(row.getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/${job}`)
    await expect(row.locator(`#fase-${job}-connessione`)).toHaveValue(CONNECTION)
    await expect(row.locator(`#fase-${job}-modello`)).toHaveValue(`modello/${job}`)
  }
  const data = await settings(page)
  expect(Object.fromEntries(data.phases.map((p) => [p.job, [p.connection, p.model]]))).toEqual(
    Object.fromEntries(JOBS.map((job) => [job, [CONNECTION, `modello/${job}`]])),
  )
  await expectNoSecretIn(page)
})

test('route secondaria di una fase', async ({ page }) => {
  await loginViaLink(page)
  const cred = (await settings(page)).connections.find((c) => c.name === CONNECTION)!.credentials[0].name
  await page.goto('/impostazioni/modelli')
  const card = await section(page, 'Route avanzate')
  await card.getByLabel('Fase').selectOption('rewrite')
  await card.getByLabel('Ruolo').selectOption('secondary')
  await card.getByLabel('Provider della route').selectOption('openai_compatible')
  await card.getByLabel('Chiave').selectOption(cred)
  await card.getByLabel('Modello della route').fill('secondario/e2e')
  await card.getByLabel('Base URL della route').fill(BASE_URL)
  await card.getByRole('button', { name: 'Salva route' }).click()
  await expect(card.getByRole('status')).toHaveText('Salvato.')

  await page.reload()
  await expect(page).toHaveURL(/fase=rewrite&ruolo=secondary/)
  await expect(card.getByLabel('Provider della route')).toHaveValue('openai_compatible')
  await expect(card.getByLabel('Chiave')).toHaveValue(cred)
  await expect(card.getByLabel('Modello della route')).toHaveValue('secondario/e2e')
  await expect(card.getByLabel('Base URL della route')).toHaveValue(BASE_URL)
  const route = await apiGet<{ credential: string; model: string; base_url: string }>(page.request, '/settings/routes/rewrite/secondary')
  expect(route).toMatchObject({ credential: cred, model: 'secondario/e2e', base_url: BASE_URL })
})

test('chiavi: stato impostata/mancante, sostituzione e prova con esito', async ({ page }) => {
  await loginViaLink(page)
  const data = await settings(page)
  const first = data.connections.find((c) => c.name === CONNECTION)!.credentials[0].name
  const cred = data.credentials.find((c) => c.name === first)!
  await page.goto('/impostazioni/chiavi')
  const row = page.locator(`[data-testid=secret-row][data-name="${cred.env_var}"]`)
  await expect(row.getByText('Impostata')).toBeVisible()
  await row.locator('input[type=password]').fill(KEY_2)
  await row.getByRole('button', { name: 'Salva' }).click()
  await expect(row.getByRole('status').filter({ hasText: 'Chiave salvata.' })).toBeVisible()
  await page.reload()
  await expect(row.getByText('Impostata')).toBeVisible()
  await expect(row.locator('input[type=password]')).toHaveValue('')
  await expectNoSecretIn(page)

  // Prova: job credential_test eseguito dal worker, esito sanificato nella pagina.
  await expect(row.getByLabel(`Modello per provare ${cred.name}`)).toHaveValue('modello/outline')
  await row.getByRole('button', { name: 'Prova' }).click()
  await expect(row.getByTestId('credential-test-result')).toContainText('Non riuscita', { timeout: 45_000 })
  await expectNoSecretIn(page)
  const jobs = await apiGet<{ type: string; state: string; result: { ok: boolean } | null }[]>(page.request, '/jobs?limit=5')
  const tested = jobs.find((j) => j.type === 'credential_test')!
  expect(tested.state).toBe('succeeded')
  expect(tested.result?.ok).toBe(false)

  // Il token del bot salvato prima risulta impostato; la chiave STT anche.
  await expect(page.locator('[data-testid=secret-row][data-name=RT_TELEGRAM_BOT_TOKEN]').getByText('Impostata')).toBeVisible()
  await expect(page.locator('[data-testid=secret-row][data-name=RT_STT_API_KEY]').getByText('Impostata')).toBeVisible()
})

test('pricing: aggiungi, ricarica, rileggi, togli', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/costi')
  const card = await section(page, 'Pricing')
  await card.getByLabel('Provider 1', { exact: true }).fill('openai_compatible')
  await card.getByLabel('Modello 1', { exact: true }).fill('modello/outline')
  await card.getByLabel('Input 1', { exact: true }).fill('0,15')
  await card.getByLabel('Output 1', { exact: true }).fill('0.6')
  await card.getByRole('button', { name: 'Aggiungi modello' }).click()
  await card.getByLabel('Provider 2', { exact: true }).fill('openrouter')
  await card.getByLabel('Modello 2', { exact: true }).fill('altro/modello')
  await card.getByLabel('Input 2', { exact: true }).fill('1')
  await card.getByLabel('Output 2', { exact: true }).fill('2')
  await card.getByLabel('Reasoning 2', { exact: true }).fill('3')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')

  await page.reload()
  await expect(card.getByTestId('pricing-row')).toHaveCount(2)
  await expect(card.getByLabel('Modello 1', { exact: true })).toHaveValue('modello/outline')
  await expect(card.getByLabel('Input 1', { exact: true })).toHaveValue('0.15')
  expect((await settings(page)).pricing).toEqual({
    openai_compatible: { 'modello/outline': { input_per_million: 0.15, output_per_million: 0.6 } },
    openrouter: { 'altro/modello': { input_per_million: 1, output_per_million: 2, reasoning_per_million: 3 } },
  })

  await card.getByLabel('Input 1', { exact: true }).fill('tanto')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('alert')).toContainText('inserisci un prezzo')

  await card.getByRole('button', { name: 'Rimuovi riga 2' }).click()
  await card.getByLabel('Input 1', { exact: true }).fill('0.2')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')
  await page.reload()
  await expect(card.getByTestId('pricing-row')).toHaveCount(1)
  expect((await settings(page)).pricing).toEqual({
    openai_compatible: { 'modello/outline': { input_per_million: 0.2, output_per_million: 0.6 } },
  })
})

test('configurazione guidata: passi salvati sul backend e ripresi dopo la ricarica', async ({ page }) => {
  const root = serverState().lessons_root
  await loginViaLink(page)
  await page.goto('/impostazioni')
  await page.getByRole('link', { name: 'Configurazione guidata' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/configurazione$/)
  await expect(page.getByLabel('Cartella delle lezioni')).toHaveValue(root)
  await page.getByRole('button', { name: 'Salva e continua' }).click()
  await expect(page).toHaveURL(/passo=2/)

  // La connessione esiste già: si prosegue.
  await expect(page.getByText(`Connessioni già configurate: ${CONNECTION}`)).toBeVisible()
  await page.getByRole('button', { name: 'Continua', exact: true }).click()
  await expect(page).toHaveURL(/passo=3/)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Modelli', level: 2 })).toBeVisible()

  await page.getByLabel('Connessione').selectOption(CONNECTION)
  await page.getByLabel('Modello').fill('modello/unico')
  await page.getByRole('button', { name: 'Usa per tutte le fasi' }).click()
  await expect(page).toHaveURL(/passo=4/)
  expect((await settings(page)).phases.every((p) => p.connection === CONNECTION && p.model === 'modello/unico')).toBe(true)

  await page.getByRole('button', { name: 'Salta' }).click()
  await expect(page).toHaveURL(/passo=5/)
  await page.reload()
  const steps = page.getByRole('list', { name: 'Passi' })
  for (const label of ['Cartella dati', 'Connessione', 'Modelli', 'Telegram']) {
    await expect(steps.getByRole('button', { name: new RegExp(label) }).getByLabel('completato')).toBeVisible()
  }
  await page.getByRole('link', { name: 'Vai alle lezioni' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/impostazioni/modelli')
  for (const job of JOBS) {
    await expect(page.locator(`[data-testid=phase-row][data-job="${job}"]`).getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/unico`)
  }
})

test('le scritture non valide mostrano il messaggio dell\'API', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const card = await section(page, 'Cartella dati')
  await card.getByLabel('Cartella delle lezioni').fill('relativa/non/valida')
  await card.getByRole('button', { name: 'Salva' }).click()
  await expect(card.getByRole('alert')).toContainText('percorso assoluto')
  await page.reload()
  await expect(card.getByLabel('Cartella delle lezioni')).toHaveValue(serverState().lessons_root)
  const res = await page.request.get('/api/v1/settings', { headers: authHeaders() })
  expect(((await res.json()) as Settings).lessons_root).toBe(serverState().lessons_root)
})
