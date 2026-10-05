import type { Settings } from '@/api/settings'

export const testSettings: Settings = {
  setup_required: false, secrets_encrypted: true, data_dir: '/tmp/rt',
  worker: { concurrency: 2, running: 2 }, notices: { dismissed: [] },
  preferences: { secondi_approvazione: 10, sfondo_gruppi: 'colori', modalita_arricchimento: 'manuale' },
  transcription: { engine: 'macparakeet', api_key_set: false },
  telegram: { enabled: false, bot_token_set: false, chat_id_set: false, topics: {}, default_channel: 'web' },
  connections: [{ name: 'locale', provider: 'openai_compatible', base_url: 'http://localhost:9/v1', models: ['test'], credentials: [{ name: 'locale_1', set: true }] }],
  credentials: [{ name: 'locale_1', provider: 'openai_compatible', env_var: 'RT_LOCALE_1_API_KEY', set: true }],
  phases: ['outline', 'rewrite', 'review', 'recall', 'image_description', 'enrichment_writer', 'enrichment_visualizer', 'enrichment_image'].map(job => ({ job, label: job, connection: 'locale', model: 'test' })),
  pricing: {}, web_search: { searxng_base_url: '' },
}
export const enrichmentSettings = { mode: 'manual' as const, automatic: false, cap_mode: 'fixed' as const, cap_number: 5, utility_threshold: 0.5,
  decision_model: 'jev/test', decision_credential: 'locale_1', decision_base_url: 'http://localhost:9/v1' }
