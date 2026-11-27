import type { Settings } from '@/api/settings'

export const testSettings: Settings = {
  setup_required: false, secrets_encrypted: true, data_dir: '/tmp/rt',
  worker: { running: 2 }, notices: { dismissed: [] },
  preferences: { modalita_scaletta: 'auto', secondi_approvazione: 10, sfondo_gruppi: 'colori', modalita_arricchimento: 'manuale', chiusura_x: 'background', avvia_all_accesso: true },
  rewrite: { context_mode: 'macro', parallel_macros: 4 },
  transcription: {
    engine: 'parakeet',
    api_key_set: false,
    recommended: 'parakeet',
    effective_engine: 'parakeet',
    macparakeet_fallback: false,
    macparakeet_available: true,
    macparakeet_installed: true,
    parakeet_available: true,
    parakeet_model_ready: false,
  },
  telegram: {
    enabled: false,
    bot_token_set: false,
    chat_id_set: false,
    notify: { lezione_pronta: true, verifica_pronta: true, errore: true, scaletta_da_approvare: true, issue_da_decidere: true },
  },
  connections: [{ name: 'locale', provider: 'openai_compatible', base_url: 'http://localhost:9/v1', models: ['test'], credentials: [{ name: 'locale_1', set: true }], supports_batch: false }],
  credentials: [{ name: 'locale_1', provider: 'openai_compatible', env_var: 'RT_LOCALE_1_API_KEY', set: true }],
  phases: ['outline', 'rewrite', 'review', 'recall', 'image_description', 'enrichment_writer', 'enrichment_visualizer', 'enrichment_image'].map(job => ({ job, label: job, connection: 'locale', model: 'test', batch: false })),
  pricing: {}, web_search: { searxng_base_url: '', contextual_verification: false },
}
export const enrichmentSettings = { mode: 'manual' as const, automatic: false, cap_mode: 'fixed' as const, cap_number: 5, utility_threshold: 0.5,
  decision_model: 'jev/test', decision_credential: 'locale_1', decision_base_url: 'http://localhost:9/v1' }
