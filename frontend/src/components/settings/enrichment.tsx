import { useState, type FormEvent } from 'react'
import { errorMessage } from '@/api/client'
import { useEnrichmentSettings, useSaveEnrichmentSettings, type EnrichmentSettings } from '@/api/enrichment'
import type { Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field, Section, SettingsSelect as Select, SaveFeedback } from './common'

export function EnrichmentSettingsSection({ settings, decisions = false }: { settings: Settings; decisions?: boolean }) {
  const query = useEnrichmentSettings()
  const save = useSaveEnrichmentSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return query.data ? <EnrichmentForm key={JSON.stringify(query.data)} settings={query.data} credentials={settings.credentials} decisions={decisions} save={save} /> : <p className="text-body">Carico l’arricchimento…</p>
}

function EnrichmentForm({ settings, credentials, decisions, save }: { settings: EnrichmentSettings; credentials: Settings['credentials']; decisions: boolean; save: ReturnType<typeof useSaveEnrichmentSettings> }) {
  const [draft, setDraft] = useState(settings)
  const set = <K extends keyof EnrichmentSettings>(key: K, value: EnrichmentSettings[K]) => setDraft(old => ({ ...old, [key]: value }))
  function submit(e: FormEvent) { e.preventDefault(); save.mutate({ ...draft, automatic: draft.mode === 'automatic' }) }
  return <Section id={decisions ? 'arricchimento-decisionale' : 'arricchimento'} title={decisions ? 'Modello decisionale dell’arricchimento' : 'Arricchimento'}>
    <form onSubmit={submit} className="flex flex-col gap-3">
      {decisions ? <>
        <Field label="Modello decisionale" htmlFor="enrichment-decision-model"><Input id="enrichment-decision-model" required value={draft.decision_model} onChange={e => set('decision_model', e.target.value)} /></Field>
        <Field label="Credenziale dell’arricchimento" htmlFor="enrichment-decision-credential"><Select id="enrichment-decision-credential" value={draft.decision_credential} onChange={e => set('decision_credential', e.target.value)}>
          <option value="">Scegli…</option>{credentials.map(c => <option key={c.name} value={c.name}>{c.name}{c.set ? '' : ' (mancante)'}</option>)}
        </Select></Field>
        <Field label="Endpoint Decision API" htmlFor="enrichment-decision-url"><Input id="enrichment-decision-url" required type="url" value={draft.decision_base_url} onChange={e => set('decision_base_url', e.target.value)} /></Field>
      </> : <>
        <Field label="Modalità dell’arricchimento" htmlFor="enrichment-mode"><Select id="enrichment-mode" value={draft.mode ?? 'manual'} onChange={e => setDraft(old => ({ ...old, mode: e.target.value as EnrichmentSettings['mode'], automatic: e.target.value === 'automatic' }))}>
          <option value="disabled">Disattivato</option><option value="manual">Manuale</option><option value="automatic">Automatico</option>
        </Select></Field>
        <Field label="Tetto globale" htmlFor="global-enrichment-cap"><Select id="global-enrichment-cap" value={draft.cap_mode} onChange={e => set('cap_mode', e.target.value as EnrichmentSettings['cap_mode'])}>
          <option value="proportional">Proporzionale: numero di subunità</option><option value="fixed">Numero fisso</option><option value="off">Disattivato</option>
        </Select></Field>
        <Field label="Numero massimo" htmlFor="global-enrichment-number"><Input id="global-enrichment-number" type="number" required min={1} max={1000} disabled={draft.cap_mode !== 'fixed'} value={draft.cap_number} onChange={e => set('cap_number', e.target.valueAsNumber)} /></Field>
        <Field label="Utilità minima (0–1)" htmlFor="enrichment-utility"><Input id="enrichment-utility" type="number" required min={0} max={1} step={0.05} value={draft.utility_threshold} onChange={e => set('utility_threshold', e.target.valueAsNumber)} /></Field>
      </>}
      <Button type="submit" className="self-start" disabled={save.isPending}>Salva arricchimento</Button>
      <SaveFeedback mutation={save} />
    </form>
  </Section>
}
