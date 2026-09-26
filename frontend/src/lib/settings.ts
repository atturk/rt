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
  { value: 'timeout', label: 'Fallback: timeout' },
  { value: 'rate_limit', label: 'Fallback: limite di richieste' },
  { value: 'safety', label: 'Fallback: filtro di sicurezza' },
  { value: 'auth', label: 'Fallback: errore di autenticazione' },
  { value: 'generic', label: 'Fallback: altri errori' },
] as const

/** Segreti fuori dalle credenziali, come EXTRA_SECRET_NAMES in rt/services/secrets_service.py. */
export const EXTRA_SECRETS = [
  { name: 'RT_TELEGRAM_BOT_TOKEN', label: 'Token del bot Telegram' },
  { name: 'RT_STT_API_KEY', label: 'Chiave del server di trascrizione' },
] as const

/** Link a un messaggio di un topic ('https://t.me/c/1234567890/12/34') -> chat e topic,
 * come parse_telegram_topic_link di rt/tui/configure. */
export function parseTopicLink(link: string): { chatId: string; topicId: number } | null {
  const m = /t\.me\/c\/(\d+)\/(\d+)/.exec(link.trim())
  if (!m) return null
  return { chatId: `-100${m[1]}`, topicId: Number(m[2]) }
}

export type TopicRow = { materia: string; topic: string }

export function topicsToRows(topics: Record<string, number>): TopicRow[] {
  return Object.entries(topics)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([materia, topic]) => ({ materia, topic: String(topic) }))
}

/** Righe del form -> mappa per PUT /settings/telegram; errore leggibile se un id non è un numero. */
export function rowsToTopics(rows: TopicRow[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const row of rows) {
    const materia = row.materia.trim().toUpperCase()
    const topic = row.topic.trim()
    if (!materia && !topic) continue
    if (!materia) throw new Error(`Manca la materia del topic ${topic}.`)
    if (!/^\d+$/.test(topic)) throw new Error(`Il topic di ${materia} deve essere un numero.`)
    out[materia] = Number(topic)
  }
  return out
}

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
