import { useState, type FormEvent } from 'react'
import { errorMessage } from '@/api/client'
import { useEnrichmentSettings, useSaveEnrichmentSettings, type EnrichmentSettings } from '@/api/enrichment'
import type { Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field, Section, SettingsSelect as Select, SaveFeedback } from './common'

export function EnrichmentSettingsSection({ decisions = false }: { settings: Settings; decisions?: boolean }) {
  const query = useEnrichmentSettings()
  const save = useSaveEnrichmentSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return query.data ? <EnrichmentForm key={JSON.stringify(query.data)} settings={query.data} decisions={decisions} save={save} /> : <p className="text-body">Carico l’arricchimento…</p>
}

function EnrichmentForm({ settings, decisions, save }: { settings: EnrichmentSettings; decisions: boolean; save: ReturnType<typeof useSaveEnrichmentSettings> }) {
  const [draft, setDraft] = useState(settings)
  const set = <K extends keyof EnrichmentSettings>(key: K, value: EnrichmentSettings[K]) => setDraft(old => ({ ...old, [key]: value }))
  function submit(e: FormEvent) { e.preventDefault(); save.mutate({ ...draft, automatic: draft.mode === 'automatic' }) }
  return <Section id={decisions ? 'arricchimento-decisionale' : 'arricchimento'} title={decisions ? 'Modello decisionale dell’arricchimento' : 'Arricchimento'}>
    <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label="Tetto globale" htmlFor="global-enrichment-cap"><Select id="global-enrichment-cap" value={draft.cap_mode} onChange={e => set('cap_mode', e.target.value as EnrichmentSettings['cap_mode'])}>
          <option value="proportional">Proporzionale: numero di subunità</option><option value="fixed">Numero fisso</option><option value="off">Disattivato</option>
        </Select></Field>
        <Field label="Numero massimo" htmlFor="global-enrichment-number"><Input id="global-enrichment-number" type="number" required min={1} max={1000} disabled={draft.cap_mode !== 'fixed'} value={draft.cap_number} onChange={e => set('cap_number', e.target.valueAsNumber)} /></Field>
        <Field label="Utilità minima (0–1)" htmlFor="enrichment-utility"><Input id="enrichment-utility" type="number" required min={0} max={1} step={0.05} value={draft.utility_threshold} onChange={e => set('utility_threshold', e.target.valueAsNumber)} /></Field>
      <Button type="submit" className="self-start" disabled={save.isPending}>Salva arricchimento</Button>
      <SaveFeedback mutation={save} />
    </form>
  </Section>
}
