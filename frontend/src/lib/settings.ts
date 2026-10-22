/** Funzioni pure della schermata Impostazioni (RT4-F5), testate con Vitest. */

export const PROVIDERS = [
  { value: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { value: 'google', label: 'Google AI Studio', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { value: 'openai_compatible', label: 'OpenAI-compatible', baseUrl: '' },
] as const

export type Provider = (typeof PROVIDERS)[number]['value']

export function providerLabel(value: string): string {
  return PROVIDERS.find((p) => p.value === value)?.label ?? value
}

export function defaultBaseUrl(provider: string): string {
  return PROVIDERS.find((p) => p.value === provider)?.baseUrl ?? ''
}

/** Ruoli di una route LLM, come ROUTE_ROLES in rt/services/settings_service.py. */
export const ROUTE_ROLES = [
  { value: 'primary', label: 'Primaria' },
  { value: 'secondary', label: 'Secondaria' },
] as const

/** Segreti fuori dalle credenziali, come EXTRA_SECRET_NAMES in rt/services/secrets_service.py. */
export const EXTRA_SECRETS = [
  { name: 'RT_TELEGRAM_BOT_TOKEN', label: 'Token del bot Telegram' },
  { name: 'RT_STT_API_KEY', label: 'Chiave del server di trascrizione' },
] as const

export type PricingRow = { provider: string; model: string; input: string; output: string; reasoning: string }
type PricingValues = { input_per_million?: number; output_per_million?: number; reasoning_per_million?: number | null }
export type Pricing = Record<string, Record<string, PricingValues | Record<string, unknown>>>

export function pricingToRows(pricing: Pricing): PricingRow[] {
  const rows: PricingRow[] = []
  for (const [provider, models] of Object.entries(pricing)) {
    for (const [model, raw] of Object.entries(models)) {
      const v = raw as PricingValues
      rows.push({
        provider,
        model,
        input: v.input_per_million == null ? '' : String(v.input_per_million),
        output: v.output_per_million == null ? '' : String(v.output_per_million),
        reasoning: v.reasoning_per_million == null ? '' : String(v.reasoning_per_million),
      })
    }
  }
  return rows
}

function price(value: string, what: string): number {
  const n = Number(value.trim().replace(',', '.'))
  if (!value.trim() || !Number.isFinite(n) || n < 0) throw new Error(`${what}: inserisci un prezzo in USD (es. 0,15).`)
  return n
}

/** Righe del form -> corpo di PUT /settings/pricing (sostituisce tutto il pricing custom). */
export function rowsToPricing(rows: PricingRow[]): Record<string, Record<string, Record<string, number>>> {
  const out: Record<string, Record<string, Record<string, number>>> = {}
  for (const row of rows) {
    const provider = row.provider.trim()
    const model = row.model.trim()
    if (!provider && !model && !row.input.trim() && !row.output.trim()) continue
    if (!provider || !model) throw new Error('Ogni riga del pricing vuole provider e modello.')
    const values: Record<string, number> = {
      input_per_million: price(row.input, `${model}, input`),
      output_per_million: price(row.output, `${model}, output`),
    }
    if (row.reasoning.trim()) values.reasoning_per_million = price(row.reasoning, `${model}, reasoning`)
    ;(out[provider] ??= {})[model] = values
  }
  return out
}

export const SETTINGS_SECTIONS = [
  { path: 'aspetto', label: 'Aspetto e lettura', description: 'Tema, lettura veloce, evidenziatore' },
  { path: 'domande', label: 'Domande', description: 'Tipi personalizzati per materia, modelli e prove' },
  { path: 'calendario', label: 'Calendario', description: 'Orario e lezioni mancanti' },
  { path: 'materie', label: 'Materie', description: 'Elenco usato da import, calendario e domande' },
  { path: 'editor', label: 'Editor e scorciatoie', description: 'Comandi e tasti dell’editor' },
  { path: 'lavorazione', label: 'Lavorazione delle lezioni', description: 'Trascrizione, scaletta, arricchimento, job' },
  { path: 'modelli-connessioni', label: 'Modelli e connessioni', description: 'Modelli per fase, chiavi e costi' },
  { path: 'telegram', label: 'Telegram', description: 'Notifiche nella tua chat' },
  { path: 'accesso', label: 'Accesso da iPhone', description: 'Indirizzo e QR di accesso' },
  { path: 'info-aggiornamenti', label: 'Info e aggiornamenti', description: 'Versione, canale e cartelle' },
] as const

export const SETTINGS_REDIRECTS: Record<string, string> = {
  modelli: 'modelli-connessioni', chiavi: 'modelli-connessioni', costi: 'modelli-connessioni',
  'ricerca-web': 'lavorazione', decisioni: 'modelli-connessioni', bot: 'telegram', info: 'info-aggiornamenti',
}
