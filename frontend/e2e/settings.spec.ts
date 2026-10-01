import { expect, test, type Page } from '@playwright/test'

import { apiGet, authHeaders, loginViaLink, serverState } from './support'

// RT4-F5: ogni campo si scrive dalla pagina, si ricarica e si rilegge sia dalla pagina sia
// dall'API. Nessuna risposta né pagina contiene il valore di una chiave.

type Phase = { job: string; label: string; connection: string | null; model: string | null }
type Settings = {
  data_dir: string | null
  setup_required: boolean
  transcription: { engine: string; base_url: string | null; model: string | null; api_key_set: boolean }
  telegram: {
    bot_token_set: boolean
    bot_token_preview: string | null
    chat_id_set: boolean
    chat_id_preview: string | null
    topics: Record<string, number>
    topic_names: Record<string, string>
    misc_topic_id: number | null
  }
  phases: Phase[]
  connections: { name: string; provider: string; base_url: string; models: string[]; credentials: { name: string; set: boolean }[] }[]
  credentials: { name: string; provider: string; env_var: string; set: boolean }[]
  pricing: Record<string, Record<string, Record<string, number>>>
  web_search: { searxng_base_url: string | null }
}

const settings = (page: Page) => apiGet<Settings>(page.request, '/settings')

// Connessione verso una porta chiusa: nessuna chiamata LLM può uscire dai test.
const CONNECTION = 'Server locale'
const BASE_URL = 'http://127.0.0.1:9/v1'
const KEY_1 = 'sk-e2e-prima-chiave-0123456789abcdef'
const KEY_2 = 'sk-e2e-seconda-chiave-fedcba9876543210'
const BOT_TOKEN = '123456789:AAE2E-token-del-bot-di-prova-xyz'
const STT_KEY = 'stt-e2e-chiave-trascrizione-4242'
const SECRETS = [KEY_1, KEY_2, BOT_TOKEN, STT_KEY]
const JOBS = ['outline', 'rewrite', 'review', 'recall', 'image_description', 'enrichment_writer', 'enrichment_visualizer', 'enrichment_image']

async function expectNoSecretIn(page: Page) {
  const html = await page.content()
  for (const secret of SECRETS) expect(html).not.toContain(secret)
}

async function section(page: Page, title: string) {
  return page.getByRole('region', { name: title, exact: true })
}

test.describe.configure({ mode: 'serial' })

test('cartella dati: solo informativa, nessuna cartella delle lezioni da scegliere', async ({ page }) => {
  await loginViaLink(page)
  await page.getByRole('navigation', { name: 'Strumenti' }).getByRole('link', { name: 'Impostazioni' }).click()
  await expect(page).toHaveURL(/\/impostazioni$/)
  const card = await section(page, 'Cartella dati')
  await expect(card.getByTestId('data-dir')).toHaveText((await settings(page)).data_dir!)
  // Le lezioni stanno nel database: niente campo né pulsante per sceglierne la cartella.
  await expect(page.getByLabel('Cartella delle lezioni')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Scegli cartella…' })).toHaveCount(0)
  await expect(page.getByText(/cartella delle lezioni/i)).toHaveCount(0)
  expect((await settings(page)).setup_required).toBe(false)
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
  await card.getByLabel('Token del bot', { exact: true }).fill(BOT_TOKEN)
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
  await expect(rows).toHaveCount(2)
  await expect(card.getByLabel('Materia 1', { exact: true })).toHaveValue('BIOCHIMICA')
  await expect(card.getByLabel('Topic 1', { exact: true })).toHaveValue('12')
  await expect(card.getByLabel('Materia 2', { exact: true })).toHaveValue('FISIOLOGIA')
  await expect(card.getByLabel('Topic 2', { exact: true })).toHaveValue('27')
  await expect(card.getByLabel('Topic generale (facoltativo)')).toHaveValue('3')
  // Il pannello del bot (RT4-F6) sta anche nelle impostazioni.
  await expect(page.getByTestId('telegram-bot')).toBeVisible()
  const tg = (await settings(page)).telegram
  expect(tg).toMatchObject({ bot_token_set: true, chat_id_set: true, topics: { BIOCHIMICA: 12, FISIOLOGIA: 27 }, misc_topic_id: 3 })

  // Token e Chat ID: campi vuoti, anteprima parzialmente nascosta e occhio per il valore completo
  // (chiesto all'API solo al clic: la risposta delle impostazioni ha solo l'anteprima).
  await expect(card.getByLabel('Token del bot', { exact: true })).toHaveValue('')
  await expect(card.getByLabel('Chat ID del gruppo')).toHaveValue('')
  await expect(card.getByTestId('bot_token-value')).toHaveText('1234…-xyz')
  await expect(card.getByTestId('chat_id-value')).toHaveText('-100…7890')
  expect(tg).toMatchObject({ bot_token_preview: '1234…-xyz', chat_id_preview: '-100…7890' })
  await expectNoSecretIn(page)
  await card.getByRole('button', { name: 'Mostra token del bot' }).click()
  await expect(card.getByTestId('bot_token-value')).toHaveText(BOT_TOKEN)
  await card.getByRole('button', { name: 'Mostra Chat ID' }).click()
  await expect(card.getByTestId('chat_id-value')).toHaveText('-1001234567890')
  await card.getByRole('button', { name: 'Nascondi token del bot' }).click()
  await expect(card.getByTestId('bot_token-value')).toHaveText('1234…-xyz')
  await expectNoSecretIn(page)

  // Un topic tolto sparisce anche dal backend (qui tutti: li ritrova l'ascolto).
  await card.getByRole('button', { name: 'Rimuovi topic 2' }).click()
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await page.reload()
  await expect(rows).toHaveCount(1)
  expect((await settings(page)).telegram.topics).toEqual({ BIOCHIMICA: 12 })
  await card.getByRole('button', { name: 'Rimuovi topic 1' }).click()
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()
  expect((await settings(page)).telegram.topics).toEqual({})

  // "Ascolta i topic": job del worker contro la Bot API finta del server e2e. Il nome del topic
  // arriva da Telegram; BIOCHIMICA coincide con una materia nota e viene proposta.
  await page.reload()
  await card.getByRole('button', { name: 'Ascolta i topic per 20 secondi' }).click()
  await expect(card.getByTestId('listen-result')).toHaveText('Rilevati 3 topic. Assegna una materia a ciascuno e salva.', { timeout: 30_000 })
  await expect(rows).toHaveCount(3)
  await expect(card.getByLabel('Topic 1', { exact: true })).toHaveValue('12')
  await expect(card.getByLabel('Materia 1', { exact: true })).toHaveValue('BIOCHIMICA')
  await expect(rows.nth(0).getByTestId('topic-name')).toHaveText('Nome su Telegram: Biochimica')
  await expect(card.getByLabel('Topic 2', { exact: true })).toHaveValue('27')
  await expect(card.getByLabel('Materia 2', { exact: true })).toHaveValue('')
  await expect(rows.nth(1).getByTestId('topic-name')).toHaveText('Nome su Telegram: Anatomia umana')
  await expect(card.getByLabel('Topic 3', { exact: true })).toHaveValue('33')
  await expect(rows.nth(2).getByTestId('topic-name')).toHaveCount(0) // nome non recuperabile
  await card.getByLabel('Materia 2', { exact: true }).fill('ANATOMIA')
  await card.getByRole('button', { name: 'Rimuovi topic 3' }).click()
  await card.getByRole('button', { name: 'Salva Telegram' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()
  await page.reload()
  await expect(rows).toHaveCount(2) // in ordine di materia
  await expect(card.getByLabel('Materia 1', { exact: true })).toHaveValue('ANATOMIA')
  await expect(rows.nth(0).getByTestId('topic-name')).toHaveText('Nome su Telegram: Anatomia umana')
  await expect(rows.nth(1).getByTestId('topic-name')).toHaveText('Nome su Telegram: Biochimica')
  const saved = (await settings(page)).telegram
  expect(saved.topics).toEqual({ ANATOMIA: 27, BIOCHIMICA: 12 })
  expect(saved.topic_names).toEqual({ '12': 'Biochimica', '27': 'Anatomia umana' })

  // "Prova" accanto al cestino: messaggio nel topic, esito visibile.
  await rows.nth(0).getByRole('button', { name: 'Prova topic 1' }).click()
  await expect(rows.nth(0).getByTestId('topic-test-result')).toHaveText('Messaggio inviato nel topic 27.')

  // Cancellazione dei soli messaggi ricevuti durante l'ascolto, dopo conferma.
  await card.getByRole('button', { name: 'Cancella i messaggi di rilevamento' }).click()
  const confirm = card.getByRole('group', { name: 'Conferma cancellazione' })
  await expect(confirm).toContainText("i 5 messaggi ricevuti durante l'ultimo ascolto")
  await confirm.getByRole('button', { name: 'Annulla' }).click()
  await expect(confirm).toBeHidden()
  await card.getByRole('button', { name: 'Cancella i messaggi di rilevamento' }).click()
  await confirm.getByRole('button', { name: 'Sì, cancella' }).click()
  const cleanup = card.getByTestId('cleanup-result')
  await expect(cleanup).toContainText('Eliminati 4 messaggi.')
  await expect(cleanup).toContainText('Non eliminati: 1')
  await expect(cleanup).toContainText('Messaggio 42: più vecchio di 48 ore (limite di Telegram)')
  await page.reload()
  await expect(card.getByRole('button', { name: 'Cancella i messaggi di rilevamento' })).toBeDisabled()
  await expect(card.getByText("I messaggi dell'ultimo ascolto sono già stati cancellati.")).toBeVisible()
  const listened = await apiGet<{ count: number; cleaned: boolean }>(page.request, '/settings/telegram/listen-messages')
  expect(listened).toMatchObject({ count: 5, cleaned: true })
  await expectNoSecretIn(page)
})

test('connessione nuova e un modello per ciascuna fase', async ({ page }) => {
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
  await row.locator('input[data-secret]').fill(KEY_2)
  await row.getByRole('button', { name: 'Salva' }).click()
  await expect(row.getByRole('status').filter({ hasText: 'Chiave salvata.' })).toBeVisible()
  await page.reload()
  await expect(row.getByText('Impostata')).toBeVisible()
  await expect(row.locator('input[data-secret]')).toHaveValue('')
  await expectNoSecretIn(page)

  // Prova: job credential_test eseguito dal worker del server e2e (rt worker --mock, nessuna
  // chiamata di rete), esito sanificato nella pagina.
  await expect(row.getByLabel(`Modello per provare ${cred.name}`)).toHaveValue('modello/outline')
  await row.getByRole('button', { name: 'Prova' }).click()
  await expect(row.getByTestId('credential-test-result')).toHaveText('Riuscita: Mock: nessuna chiamata di rete.', { timeout: 30_000 })
  await expectNoSecretIn(page)
  const jobs = await apiGet<{ type: string; state: string; result: { ok: boolean } | null }[]>(page.request, '/jobs?limit=5')
  const tested = jobs.find((j) => j.type === 'credential_test')!
  expect(tested.state).toBe('succeeded')
  expect(tested.result?.ok).toBe(true)

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
  await card.getByLabel('IN 1', { exact: true }).fill('0,15')
  await card.getByLabel('OUT 1', { exact: true }).fill('0.6')
  await card.getByRole('button', { name: 'Aggiungi modello' }).click()
  await card.getByLabel('Provider 2', { exact: true }).fill('openrouter')
  await card.getByLabel('Modello 2', { exact: true }).fill('altro/modello')
  await card.getByLabel('IN 2', { exact: true }).fill('1')
  await card.getByLabel('OUT 2', { exact: true }).fill('2')
  await card.getByLabel('R 2', { exact: true }).fill('3')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')

  await page.reload()
  await expect(card.getByTestId('pricing-row')).toHaveCount(2)
  await expect(card.getByLabel('Modello 1', { exact: true })).toHaveValue('modello/outline')
  await expect(card.getByLabel('IN 1', { exact: true })).toHaveValue('0.15')
  expect((await settings(page)).pricing).toEqual({
    openai_compatible: { 'modello/outline': { input_per_million: 0.15, output_per_million: 0.6 } },
    openrouter: { 'altro/modello': { input_per_million: 1, output_per_million: 2, reasoning_per_million: 3 } },
  })

  await card.getByLabel('IN 1', { exact: true }).fill('tanto')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('alert')).toContainText('inserisci un prezzo')

  await card.getByRole('button', { name: 'Rimuovi riga 2' }).click()
  await card.getByLabel('IN 1', { exact: true }).fill('0.2')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')
  await page.reload()
  await expect(card.getByTestId('pricing-row')).toHaveCount(1)
  expect((await settings(page)).pricing).toEqual({
    openai_compatible: { 'modello/outline': { input_per_million: 0.2, output_per_million: 0.6 } },
  })
})

test('configurazione guidata: passi salvati sul backend e ripresi dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  await page.getByRole('link', { name: 'Configurazione guidata' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/configurazione$/)
  // Nessun passo per la cartella delle lezioni: si parte dalla connessione.
  await expect(page.getByLabel('Cartella delle lezioni')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Connessione', level: 2 })).toBeVisible()

  // La connessione esiste già: si prosegue.
  await expect(page.getByText(`Connessioni già configurate: ${CONNECTION}`)).toBeVisible()
  await page.getByRole('button', { name: 'Continua', exact: true }).click()
  await expect(page).toHaveURL(/passo=2/)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Modelli', level: 2 })).toBeVisible()

  await page.getByLabel('Connessione').selectOption(CONNECTION)
  await page.getByLabel('Modello', { exact: true }).fill('modello/unico')
  await page.getByRole('button', { name: 'Usa per tutte le fasi' }).click()
  await expect(page).toHaveURL(/passo=3/)
  expect((await settings(page)).phases.every((p) => p.connection === CONNECTION && p.model === 'modello/unico')).toBe(true)

  // Telegram già configurato: anteprime con l'occhio anche nel passo guidato.
  await expect(page.getByTestId('chat_id-value')).toHaveText('-100…7890')
  await page.getByRole('button', { name: 'Mostra Chat ID' }).click()
  await expect(page.getByTestId('chat_id-value')).toHaveText('-1001234567890')
  await page.getByRole('button', { name: 'Salta' }).click()
  await expect(page).toHaveURL(/passo=4/)
  await page.reload()
  const steps = page.getByRole('list', { name: 'Passi' })
  await expect(steps.getByRole('button')).toHaveText([/Connessione/, /Modelli/, /Telegram/, /Fatto/])
  for (const label of ['Connessione', 'Modelli', 'Telegram']) {
    await expect(steps.getByRole('button', { name: new RegExp(label) }).getByLabel('completato')).toBeVisible()
  }
  await page.getByRole('link', { name: 'Vai alle lezioni' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/impostazioni/modelli')
  for (const job of JOBS) {
    await expect(page.locator(`[data-testid=phase-row][data-job="${job}"]`).getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/unico`)
  }
})

test('modelli per fase: Prova prima di salvare (in mock) con esito e latenza', async ({ page }) => {
  await loginViaLink(page)
  const before = (await settings(page)).phases
  await page.goto('/impostazioni/modelli')
  const row = page.locator('[data-testid=phase-row][data-job="review"]')
  await row.locator('#fase-review-modello').fill('modello/non-salvato')
  await row.getByRole('button', { name: 'Prova il modello di Review' }).click()
  await expect(row.getByTestId('model-test-result')).toHaveText('Raggiungibile · 0 ms · Mock: nessuna chiamata di rete.')
  // La prova non salva: il backend ha ancora il modello di prima.
  expect((await settings(page)).phases).toEqual(before)
  // Cambiando il modello l'esito sparisce (vale per il valore provato).
  await row.locator('#fase-review-modello').fill('modello/altro')
  await expect(row.getByTestId('model-test-result')).toHaveCount(0)
  await page.reload()
  await expect(row.locator('#fase-review-modello')).toHaveValue(before.find((p) => p.job === 'review')!.model!)
})

test('configurazione guidata: scelta per ogni fase, con Prova', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/configurazione?passo=2')
  // Predefinito: lo stesso modello per tutte le fasi, provabile prima di salvare.
  await expect(page.getByRole('radio', { name: 'Usa lo stesso modello per tutte le fasi' })).toBeChecked()
  await page.getByRole('button', { name: 'Prova il modello' }).click()
  await expect(page.getByTestId('model-test-result')).toContainText('Raggiungibile')

  await page.getByRole('radio', { name: 'Scegli per ogni fase' }).check()
  await expect(page).toHaveURL(/modelli=per-fase/)
  const rows = page.getByTestId('phase-row')
  await expect(rows).toHaveCount(8)
  for (const label of ['Outline', 'Rewrite', 'Review', 'Recall', 'Descrizione immagine', 'Arricchitore', 'Visualizzazioni HTML', 'Generazione infografiche']) {
    await expect(page.getByRole('form', { name: `Fase ${label}` })).toBeVisible()
  }
  const recall = page.locator('[data-testid=phase-row][data-job="recall"]')
  await recall.locator('#fase-recall-connessione').selectOption(CONNECTION)
  await recall.locator('#fase-recall-modello').fill('modello/recall')
  await recall.getByRole('button', { name: 'Prova il modello di Recall' }).click()
  await expect(recall.getByTestId('model-test-result')).toContainText('Raggiungibile')
  await recall.getByRole('button', { name: 'Salva' }).click()
  await expect(recall.getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/recall`)

  await page.reload()
  await expect(page.getByRole('radio', { name: 'Scegli per ogni fase' })).toBeChecked()
  await expect(recall.getByTestId('phase-saved')).toHaveText(`${CONNECTION} · modello/recall`)
  const phases = Object.fromEntries((await settings(page)).phases.map((p) => [p.job, p.model]))
  expect(phases.recall).toBe('modello/recall')
  expect(phases.outline).toBe('modello/unico')
  await page.getByRole('button', { name: 'Continua' }).click()
  await expect(page).toHaveURL(/passo=3/)
})

test('pricing: suggerimenti e avviso per provider o modello sconosciuti', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/costi')
  const card = await section(page, 'Pricing')
  await expect(card).toContainText('non considera il caching dei token')
  // I suggerimenti vengono dalle connessioni e dai modelli in uso.
  await expect(card.locator('#pricing-providers option[value="openai_compatible"]')).toHaveCount(1)
  await expect(card.locator('#pricing-models option[value="modello/recall"]')).toHaveCount(1)
  await card.getByRole('button', { name: 'Aggiungi modello' }).click()
  const provider = card.getByLabel('Provider 2', { exact: true })
  const model = card.getByLabel('Modello 2', { exact: true })
  await provider.fill('openai_compatible')
  await model.fill('modello/recall')
  const row = card.getByTestId('pricing-row').nth(1)
  await expect(row.getByTestId('field-warning')).toHaveCount(0)
  await provider.fill('fornitore-ignoto')
  await model.fill('modello/ignoto')
  await expect(row.getByRole('img', { name: 'Provider non configurato' })).toBeVisible()
  await expect(row.getByRole('img', { name: 'Modello non in uso' })).toBeVisible()
  await expect(provider).toHaveAccessibleDescription('Provider non configurato')
  await row.getByRole('img', { name: 'Modello non in uso' }).hover()
  await expect(row.getByRole('tooltip', { name: 'Modello non in uso' })).toBeVisible()
  // Etichette brevi con la spiegazione nel tooltip.
  await expect(card.getByLabel('R 2', { exact: true })).toHaveAccessibleDescription(
    'Costo per milione di token di ragionamento (se il provider lo fa pagare a parte)',
  )
  // È solo un avviso: si salva lo stesso.
  await card.getByLabel('IN 2', { exact: true }).fill('1')
  await card.getByLabel('OUT 2', { exact: true }).fill('2')
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')
  await page.reload()
  await expect(card.getByTestId('pricing-row')).toHaveCount(2)
  expect((await settings(page)).pricing['fornitore-ignoto']).toEqual({ 'modello/ignoto': { input_per_million: 1, output_per_million: 2 } })
  await card.getByRole('button', { name: 'Rimuovi riga 2' }).click()
  await card.getByRole('button', { name: 'Salva pricing' }).click()
  await expect(card.getByRole('status')).toHaveText('Pricing salvato.')
})

test('ricerca web: SearXNG provato, salvato e riletto dopo la ricarica', async ({ page }) => {
  const url = serverState().searxng_url
  await loginViaLink(page)
  await page.goto('/impostazioni')
  await page.getByRole('navigation', { name: 'Sezioni delle impostazioni' }).getByRole('link', { name: 'Ricerca web' }).click()
  await expect(page).toHaveURL(/\/impostazioni\/ricerca-web$/)
  const card = await section(page, 'Ricerca web')
  const field = card.getByLabel('URL base di SearXNG')
  await expect(field).toHaveAttribute('placeholder', 'http://localhost:8088')
  // Il server e2e parte con un SearXNG configurato (le immagini per unità di FA7 lo richiedono).
  await expect(field).toHaveValue('http://127.0.0.1:9')

  // Prova contro un server chiuso: errore leggibile.
  await field.fill('http://127.0.0.1:9')
  await card.getByRole('button', { name: 'Prova' }).click()
  await expect(card.getByTestId('searxng-test-result')).toContainText('Impossibile raggiungere SearXNG')

  // SearXNG finto del server e2e: tre immagini.
  await field.fill(url)
  await card.getByRole('button', { name: 'Prova' }).click()
  await expect(card.getByTestId('searxng-test-result')).toContainText('3 immagini')
  await card.getByRole('button', { name: 'Salva' }).click()
  await expect(card.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()

  await page.reload()
  await expect(field).toHaveValue(url)
  expect((await settings(page)).web_search.searxng_base_url).toBe(url)
})

test('campi segreti: niente type="password" (il portachiavi non propone password)', async ({ page }) => {
  await loginViaLink(page)
  for (const path of ['/impostazioni', '/impostazioni/modelli', '/impostazioni/chiavi']) {
    await page.goto(path)
    await expect(page.locator('input[data-secret]').first()).toBeVisible()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    for (const input of await page.locator('input[data-secret]').all()) {
      await expect(input).toHaveAttribute('type', 'text')
      await expect(input).toHaveAttribute('autocomplete', 'off')
      await expect(input).toHaveAttribute('data-1p-ignore', '')
      await expect(input).toHaveAttribute('data-lpignore', 'true')
      expect(`${await input.getAttribute('id')} ${await input.getAttribute('name')}`).not.toMatch(/password/i)
      // Il valore resta mascherato.
      expect(await input.evaluate((el) => getComputedStyle(el).getPropertyValue('-webkit-text-security'))).toBe('disc')
    }
  }
})

test('le scritture non valide mostrano il messaggio dell\'API', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const card = await section(page, 'Trascrizione')
  const before = (await settings(page)).transcription
  await card.getByLabel('Motore').selectOption('custom')
  await card.getByLabel('Base URL del server').fill('ftp://127.0.0.1/non-valido')
  await card.getByLabel('Modello').fill('whisper-e2e')
  await card.getByRole('button', { name: 'Salva trascrizione' }).click()
  await expect(card.getByRole('alert')).toContainText('Base URL HTTP valido')
  await page.reload()
  await expect(card.getByLabel('Motore')).toHaveValue(before.engine)
  const res = await page.request.get('/api/v1/settings', { headers: authHeaders() })
  expect(((await res.json()) as Settings).transcription).toEqual(before)
})

test('job in parallelo: si salva, resta dopo la ricarica e vale dal prossimo avvio', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const jobs = await section(page, 'Job')
  const select = jobs.getByLabel('Job in parallelo')
  const before = await apiGet<{ worker: { concurrency: number; running: number } }>(page.request, '/settings')
  await expect(select).toHaveValue(String(before.worker.concurrency))
  await expect(jobs).toContainText('vale dal prossimo avvio di RT')
  await select.selectOption('3')
  await jobs.getByRole('button', { name: 'Salva' }).click()
  await expect(jobs.getByRole('status')).toContainText('prossimo avvio')
  await page.reload()
  await expect((await section(page, 'Job')).getByLabel('Job in parallelo')).toHaveValue('3')
  expect((await apiGet<{ worker: { concurrency: number } }>(page.request, '/settings')).worker.concurrency).toBe(3)
  // il worker del server di prova è partito con il valore di prima: lo dice la pagina
  await expect(await section(page, 'Job')).toContainText(`Ora ne esegue fino a ${before.worker.running} insieme.`)
  // ripristino per gli altri test
  await page.request.put('/api/v1/settings/worker', { headers: authHeaders(), data: { concurrency: before.worker.concurrency } })
})
