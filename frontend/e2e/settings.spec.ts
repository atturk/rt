import { expect, type Locator, type Page } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, scrollDocumentTo, serverState } from './support'

const CONNECTION = 'Server locale 422'
const KEY = 'sk-e2e-chiave-422-0123456789abcdef'
const BASE_URL = 'http://127.0.0.1:9/v1'
const sections = [
  ['aspetto', 'Aspetto e lettura'], ['editor', 'Editor e scorciatoie'], ['lavorazione', 'Lavorazione delle lezioni'],
  ['modelli-connessioni', 'Modelli e connessioni'], ['telegram', 'Telegram'], ['accesso', 'Accesso da iPhone'], ['info-aggiornamenti', 'Info e aggiornamenti'],
]
async function choose(root: Page | Locator, label: string, option: string) {
  await root.getByRole('button', { name: label, exact: true }).click()
  await root.getByRole('menuitemradio', { name: option, exact: true }).click()
}
const region = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
test.describe.configure({ mode: 'serial' })

test('sette sezioni: desktop a due colonne, telefono con pagina e ritorno', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni')
  const nav = page.getByRole('navigation', { name: 'Sezioni delle impostazioni' })
  await expect(nav.getByRole('link')).toHaveCount(7)
  await expect(page.getByRole('radiogroup', { name: 'Tema' })).toBeVisible()
  const navBox = (await nav.boundingBox())!
  const themeBox = (await page.getByRole('radiogroup', { name: 'Tema' }).boundingBox())!
  expect(themeBox.x).toBeGreaterThan(navBox.x + navBox.width)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('radiogroup', { name: 'Tema' })).toHaveCount(0)
  for (const [path, label] of sections) {
    await nav.getByRole('link', { name: new RegExp(label) }).click()
    await expect(page).toHaveURL(new RegExp(`/impostazioni/${path}$`))
    await expect(page.getByRole('heading', { name: label, level: 1 })).toBeVisible()
    await expect(nav).toHaveCount(0)
    await page.locator('main header').getByRole('link', { name: 'Impostazioni', exact: true }).click()
    await expect(nav).toBeVisible()
  }
})

test('i vecchi URL aprono la sezione corrispondente', async ({ page }) => {
  await loginViaLink(page)
  for (const [old, current] of [['modelli', 'modelli-connessioni'], ['chiavi', 'modelli-connessioni'], ['costi', 'modelli-connessioni'],
    ['ricerca-web', 'lavorazione'], ['decisioni', 'modelli-connessioni'], ['bot', 'telegram'], ['info', 'info-aggiornamenti']]) {
    await page.goto(`/impostazioni/${old}?fase=rewrite`)
    await expect(page).toHaveURL(new RegExp(`/impostazioni/${current}\\?fase=rewrite`))
  }
  await page.goto('/bot')
  await expect(page).toHaveURL(/\/impostazioni\/telegram$/)
  await page.goto('/impostazioni#telegram')
  await expect(page).toHaveURL(/\/impostazioni\/telegram#telegram$/)
})

test('tema, lettura, audio e sfondo salvati su RT e riletti dopo la ricarica', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/aspetto')
  await page.getByRole('radio', { name: 'Scuro', exact: true }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await choose(page, 'Sfondo dei gruppi in Lezioni', 'Grigi')
  await page.getByRole('switch', { name: 'Frecce per cambiare unità' }).click()
  await choose(page, 'Lettera di fuoco', 'Dopo')
  await choose(page, 'Velocità di riproduzione', '1,5×')
  await expect.poll(async () => (await apiGet<Record<string, unknown>>(page.request, '/preferences'))['audio.rate']).toBe(1.5)
  await page.reload()
  await expect(page.getByTestId('pref-audio-rate')).toHaveAttribute('data-value', '1.5')
  await expect(page.getByTestId('rsvp-orp')).toHaveAttribute('data-value', 'dopo')
  await expect(page.getByRole('switch', { name: 'Frecce per cambiare unità' })).toHaveAttribute('aria-checked', 'false')
  // Le preferenze stanno su RT: le frecce tornano accese, le usano lo Studio e i test dopo questo.
  await page.getByRole('switch', { name: 'Frecce per cambiare unità' }).click()
  await expect(page.getByRole('switch', { name: 'Frecce per cambiare unità' })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByTestId('pref-sfondo')).toHaveAttribute('data-value', 'grigi')
  await page.getByRole('radio', { name: 'Sistema', exact: true }).click()
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await expect(page.locator('select')).toHaveCount(0)
})

test('lavorazione: trascrizione, scaletta, modalità unica e job', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/lavorazione')
  const stt = region(page, 'Trascrizione')
  await choose(stt, 'Motore', 'Server OpenAI-compatible')
  await stt.getByLabel('Base URL del server').fill('http://127.0.0.1:9000/v1')
  await stt.getByLabel('Modello', { exact: true }).fill('whisper-e2e')
  await stt.getByLabel('Chiave API (facoltativa)').fill('stt-e2e-chiave-422-012345')
  await stt.getByRole('button', { name: 'Salva trascrizione' }).click()
  await expect(stt.getByRole('status')).toHaveText('Salvato.')
  const outline = region(page, 'Scaletta')
  await outline.getByLabel('Approva da sola dopo (secondi)').fill('0')
  await outline.getByRole('button', { name: 'Salva scaletta' }).click()
  await expect(outline.getByRole('status')).toHaveText('Salvato.')
  const enrichment = region(page, 'Arricchimento')
  await enrichment.getByLabel('Utilità minima (0–1)').fill('0.65')
  await enrichment.getByRole('button', { name: 'Salva arricchimento' }).click()
  await expect(enrichment.getByRole('status')).toHaveText('Salvato.')
  expect(await apiGet(page.request, '/settings/enrichment')).toMatchObject({ utility_threshold: 0.65 })
  await expect(page.getByText(/Analizza anche nella pipeline/)).toHaveCount(0)
  await choose(region(page, 'Job'), 'Job in parallelo', '3')
  await region(page, 'Job').getByRole('button', { name: 'Salva', exact: true }).click()
  await expect(region(page, 'Job').getByRole('status')).toContainText('prossimo avvio')
  await page.reload()
  await expect(page.getByTestId('stt-engine')).toHaveAttribute('data-value', 'custom')
  await expect(stt.getByLabel('Chiave API (facoltativa)')).toHaveValue('')
  await expect(page.getByTestId('worker-concurrency')).toHaveAttribute('data-value', '3')
  await expect(enrichment.getByLabel('Utilità minima (0–1)')).toHaveValue('0.65')
  await page.goto('/impostazioni/aspetto')
  await choose(page, 'Sfondo dei gruppi in Lezioni', 'Colori')
  await expect.poll(async () => (await apiGet<{ preferences: { sfondo_gruppi: string } }>(page.request, '/settings')).preferences.sfondo_gruppi).toBe('colori')
  expect(await apiGet(page.request, '/settings/enrichment')).toMatchObject({ utility_threshold: 0.65 })
})

test('connessione: chiavi, modello e costi nello stesso gruppo', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/modelli-connessioni')
  const newConnection = region(page, 'Nuova connessione')
  await newConnection.getByLabel('Nome connessione').fill(CONNECTION)
  await choose(newConnection, 'Provider', 'OpenAI-compatible')
  await newConnection.getByLabel('Base URL', { exact: true }).fill(BASE_URL)
  await newConnection.getByLabel('Chiave API 1').fill(KEY)
  await newConnection.getByRole('button', { name: 'Crea connessione' }).click()
  const connection = page.getByRole('group', { name: `Connessione ${CONNECTION}` })
  await expect(connection).toBeVisible()
  await connection.getByLabel(`Nuovo modello per ${CONNECTION}`).fill('test/422')
  await connection.getByRole('button', { name: 'Aggiungi', exact: true }).click()
  await expect(connection.getByTestId('connection-models')).toContainText('test/422')
  await connection.getByLabel('Modello costo 1').fill('test/422')
  await connection.getByLabel('IN 1', { exact: true }).fill('0,15')
  await connection.getByLabel('OUT 1', { exact: true }).fill('0.6')
  await connection.getByRole('button', { name: 'Salva costi' }).click()
  await expect(connection.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()
  await page.reload()
  await expect(connection.getByLabel('IN 1', { exact: true })).toHaveValue('0.15')
  await expect(connection.getByTestId('secret-row')).toHaveCount(1)
  await expect(connection.locator('input[data-secret]')).toHaveValue('')
  expect(await page.content()).not.toContain(KEY)
  expect(await apiGet(page.request, '/settings')).toMatchObject({ pricing: { openai_compatible: { 'test/422': { input_per_million: 0.15, output_per_million: 0.6 } } } })
  await expect(page.locator('[data-name=RT_STT_API_KEY]')).toHaveCount(0)
  await expect(page.locator('[data-name=RT_TELEGRAM_BOT_TOKEN]')).toHaveCount(0)
})

test('SearXNG resta nella lavorazione, Prova e salvataggio funzionano', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/ricerca-web')
  const search = region(page, 'Ricerca web')
  await search.getByLabel('URL base di SearXNG').fill(serverState().searxng_url)
  await search.getByRole('button', { name: 'Prova', exact: true }).click()
  await expect(search.getByTestId('searxng-test-result')).toContainText('3 immagini')
  await search.getByRole('button', { name: 'Salva', exact: true }).click()
  await expect(search.getByRole('status')).toHaveText('Salvato.')
})

test('Telegram: un solo interruttore, token e topic; archivio e notifiche qui', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/telegram')
  await expect(page.getByRole('switch', { name: 'Usa Telegram' })).toHaveCount(1)
  const enabled = page.getByRole('switch', { name: 'Usa Telegram' })
  if (await enabled.getAttribute('aria-checked') === 'false') await enabled.click()
  await expect(page.getByTestId('telegram-bot')).toBeVisible()
  const tg = region(page, 'Telegram')
  await tg.getByLabel('Token del bot', { exact: true }).fill('123456789:AAE2E-token-422-xyz')
  await tg.getByLabel('Chat ID del gruppo').fill('-1001234567890')
  await tg.getByLabel('Materia 1', { exact: true }).fill('BIOCHIMICA')
  await tg.getByLabel('Topic 1', { exact: true }).fill('12')
  await tg.getByRole('button', { name: 'Salva Telegram' }).click()
  await expect(tg.getByRole('status').filter({ hasText: 'Salvato.' })).toBeVisible()
  await page.reload()
  await expect(tg.getByLabel('Token del bot', { exact: true })).toHaveValue('')
  await expect(tg.getByLabel('Topic 1', { exact: true })).toHaveValue('12')
  await expect(page.getByTestId('telegram-bot')).toHaveCount(1)
  await expect(region(page, 'Archivio dei topic')).toBeVisible()
  await expect(region(page, 'Ultime notifiche inviate')).toBeVisible()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
})

test('Info contiene la cartella dati, il wizard e l’uscita; Accesso contiene il QR', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/info')
  const info = page.getByTestId('system-info')
  const settings = await apiGet<{ data_dir: string }>(page.request, '/settings')
  await expect(info).toContainText(settings.data_dir)
  await expect(page.getByRole('link', { name: 'Configurazione guidata' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Esci', exact: true })).toBeVisible()
  await page.goto('/impostazioni/accesso')
  await page.getByLabel("Indirizzo di RT per l'altro dispositivo").fill('https://mac.tail1234.ts.net')
  await page.getByRole('button', { name: 'Crea QR di accesso' }).click()
  await expect(page.getByRole('img', { name: 'QR del link di accesso' })).toBeVisible()
})

test('wizard: il modello comune lascia intatte le fasi delle immagini', async ({ page }) => {
  await loginViaLink(page)
  await page.goto('/impostazioni/configurazione?passo=2')
  const before = await apiGet<{ phases: { job: string; connection: string | null; model: string | null }[] }>(page.request, '/settings')
  const form = page.getByRole('form', { name: 'Stesso modello per tutte le fasi' })
  await choose(form, 'Connessione', CONNECTION)
  await form.getByLabel('Modello', { exact: true }).fill('test/422')
  await form.getByRole('button', { name: 'Usa per tutte le fasi' }).click()
  await expect.poll(async () => (await apiGet<{ phases: { job: string; model: string }[] }>(page.request, '/settings')).phases.find(p => p.job === 'rewrite')?.model).toBe('test/422')
  const after = await apiGet<typeof before>(page.request, '/settings')
  for (const job of ['image_description', 'enrichment_image']) expect(after.phases.find(p => p.job === job)).toEqual(before.phases.find(p => p.job === job))
  await expect(page).toHaveURL(/passo=2/)
  await expect(page.getByTestId('phase-row')).toHaveCount(2)
})

// Le etichette delle scorciatoie dipendono dalla tastiera (⌘ sul Mac della CI): questi test fissano quella PC.
const pcKeyboard = (target: { addInitScript: Page['addInitScript'] }) =>
  target.addInitScript(() => Object.defineProperty(Navigator.prototype, 'platform', { get: () => 'Linux x86_64' }))

test('scorciatoie: registra, ritrova su un altro dispositivo e ripristina', async ({ page, browser }) => {
  await pcKeyboard(page)
  await loginViaLink(page)
  await page.goto('/impostazioni/editor')
  const bold = page.getByRole('button', { name: 'Scorciatoia: Grassetto', exact: true })
  await bold.click()
  await expect(bold).toHaveText('Premi i tasti…')
  await bold.press('Control+Shift+j')
  await expect(bold).toHaveText('Ctrl+Shift+J')
  await expect.poll(async () => (await apiGet<Record<string, unknown>>(page.request, '/preferences'))['editor.shortcuts']).toEqual({ bold: 'Mod-Shift-j' })
  const device = await browser.newContext()
  try {
    const other = await device.newPage()
    await pcKeyboard(other)
    await loginViaLink(other)
    await other.goto('/impostazioni/editor')
    await expect(other.getByRole('button', { name: 'Scorciatoia: Grassetto', exact: true })).toHaveText('Ctrl+Shift+J')
  } finally { await device.close() }
  await page.getByRole('button', { name: 'Ripristina tutte', exact: true }).click()
  await expect.poll(async () => Object.hasOwn(await apiGet(page.request, '/preferences'), 'editor.shortcuts')).toBe(false)
  await expect(bold).toHaveText('Ctrl+B')
})

test('barra editor: comandi sul testo e una riga scorrevole sul telefono', async ({ page }) => {
  await pcKeyboard(page)
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=BIOCHIMICA')
  await page.goto(`/lezioni/${lesson.id}`)
  const toolbar = page.getByRole('toolbar', { name: 'Strumenti dell’editor' })
  await expect(toolbar).toBeVisible()
  await expect(toolbar.getByRole('button')).toHaveCount(12)
  await expect(toolbar.getByRole('button', { name: /Titolo/ })).toHaveCount(0)
  const editor = page.getByTestId('lesson-document')
  const paragraph = editor.locator('.cm-line:not([data-unit-id]):not(.cm-atomic-h1):not(.cm-atomic-h2):not(.cm-atomic-h3)', { hasText: /\w+ \w+ \w+/ }).first()
  await paragraph.click()
  await page.keyboard.press('Control+End')
  await page.keyboard.press('Control+Shift+ArrowLeft')
  await page.keyboard.press('Control+Shift+ArrowLeft')
  const selected = await page.evaluate(() => window.getSelection()?.toString())
  expect(selected?.length).toBeGreaterThan(0)
  await toolbar.getByRole('button', { name: 'Grassetto (Ctrl+B)', exact: true }).click()
  await expect(toolbar.getByRole('button', { name: 'Grassetto (Ctrl+B)', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(editor.locator('.cm-activeLine')).toContainText('**')
  await toolbar.getByRole('button', { name: 'Annulla (Ctrl+Z)', exact: true }).click()
  await expect(editor.locator('.cm-activeLine')).not.toContainText('**')
  await page.setViewportSize({ width: 390, height: 844 })
  const geometry = await toolbar.evaluate(el => ({ width: el.clientWidth, scroll: el.scrollWidth, sticky: getComputedStyle(el).position,
    rows: Array.from(el.querySelectorAll('button')).map(button => Math.round(button.getBoundingClientRect().y)) }))
  expect(geometry.scroll).toBeGreaterThan(geometry.width)
  expect(new Set(geometry.rows).size).toBe(1)
  expect(geometry.sticky).toBe('sticky')
})

test('allineamenti editor: frecce sulla prima riga e testo allineato al titolo a 1280 e 390 px', async ({ page }) => {
  await loginViaLink(page)
  const [lesson] = await apiGet<{ id: number }[]>(page.request, '/lessons?materia=CHIRURGIA')
  const original = await apiGet<{ markdown: string }>(page.request, `/lessons/${lesson.id}/document`)
  const title = 'Titolo lungo con parole che proseguono sulla riga successiva e richiedono una freccia centrata sulla prima riga anche quando cambia la larghezza della pagina'
  const markdown = original.markdown.replace(/^(## \d+\. ).+$/m, `$1${title}`).replace(/^(### \d+\.\d+ ).+$/m, `$1${title}`)
    + `\n\n## Approfondimento ${title}\n\nTesto dell’approfondimento.\n\n### Dettagli ${title}\n\nUn altro paragrafo.\n`
  const lease = await page.request.post(`/api/v1/lessons/${lesson.id}/document/lease`, { headers: authHeaders() })
  expect(lease.ok()).toBeTruthy()
  const { token } = await lease.json()
  const save = await page.request.put(`/api/v1/lessons/${lesson.id}/document/draft`, { headers: authHeaders(), data: { markdown, lease_token: token } })
  expect(save.ok(), await save.text()).toBeTruthy()
  await page.request.delete(`/api/v1/lessons/${lesson.id}/document/lease?token=${encodeURIComponent(token)}`, { headers: authHeaders() })
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto(`/lezioni/${lesson.id}`)
    const editor = page.getByTestId('lesson-document')
    await expect(editor.locator('.cm-foldGutter .rt-fold-marker').first()).toBeAttached()
    // CodeMirror virtualizza le righe: ogni titolo si raggiunge per identità,
    // anche quando il testo lungo fa uscire gli altri dalla vista.
    const headings = [
      editor.locator('.cm-line.cm-atomic-h2').filter({ hasNotText: 'Approfondimento' }),
      editor.locator('.cm-line.cm-atomic-h3[data-unit-id]'),
      editor.locator('.cm-line.cm-atomic-h2').filter({ hasText: `Approfondimento ${title}` }),
      editor.locator('.cm-line.cm-atomic-h3').filter({ hasText: `Dettagli ${title}` }),
    ]
    for (const heading of headings) {
      await scrollDocumentTo(page, heading)
      await expect(heading).toHaveCount(1)
      await expect.poll(async () => heading.evaluate(line => {
        const box = line.getBoundingClientRect()
        const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-testid=lesson-document] .cm-foldGutter .cm-gutterElement')).filter(row => row.querySelector('.rt-fold-marker'))
        const row = rows.sort((a, b) => Math.abs(a.getBoundingClientRect().top - box.top) - Math.abs(b.getBoundingClientRect().top - box.top))[0]
        const marker = row.querySelector('.rt-fold-marker')!.getBoundingClientRect()
        const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT)
        let node: Node | null
        while ((node = walker.nextNode())) {
          if (!node.textContent?.trim()) continue
          const range = document.createRange()
          range.setStart(node, 0); range.setEnd(node, 1)
          const first = range.getBoundingClientRect()
          if (first.width > 0 && first.height > 0) return Math.abs(marker.top + marker.height / 2 - first.top - first.height / 2)
        }
        return Infinity
      })).toBeLessThanOrEqual(2)
      const dimensions = await heading.evaluate(line => { const style = getComputedStyle(line); return { height: line.getBoundingClientRect().height - parseFloat(style.paddingTop), lineHeight: parseFloat(style.lineHeight) } })
      expect(dimensions.height).toBeGreaterThan(dimensions.lineHeight * 1.5)
    }
    const left = await editor.locator('.cm-line').first().evaluate(line => line.getBoundingClientRect().left)
    const pageTitle = await page.getByTestId('lesson-page').locator('h1').boundingBox()
    expect(Math.abs(left - pageTitle!.x)).toBeLessThanOrEqual(2)
  }
})
