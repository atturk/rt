import { useState, type FormEvent } from 'react'
import { errorMessage } from '@/api/client'
import { useEnrichmentSettings, useSaveEnrichmentSettings, type EnrichmentSettings } from '@/api/enrichment'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Field, Section } from './common'

export function EnrichmentSettingsSection() {
  const query = useEnrichmentSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return query.data ? <EnrichmentForm key={JSON.stringify(query.data)} settings={query.data} /> : <p>Carico le impostazioni di arricchimento…</p>
}

function EnrichmentForm({ settings }: { settings: EnrichmentSettings }) {
  const [draft, setDraft] = useState(settings)
  const save = useSaveEnrichmentSettings()
  const set = <K extends keyof EnrichmentSettings>(key: K, value: EnrichmentSettings[K]) => setDraft(old => ({ ...old, [key]: value }))
  function submit(e: FormEvent) { e.preventDefault(); save.mutate(draft) }
  return <Section id="arricchimento" title="Arricchimento: decisioni e suggerimenti"
    description="Il classificatore usa la Decision API per scegliere le macro unità delle immagini e valutare l’utilità dei suggerimenti. Arricchitore, visualizzazioni e infografiche si assegnano nei ruoli modello sopra. Nessun elemento viene generato automaticamente.">
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.automatic ?? false} onChange={e => set('automatic', e.target.checked)} />Analizza anche nella pipeline (altrimenti solo dalla pagina Arricchimento)</label>
      <Field label="Tetto globale" htmlFor="global-enrichment-cap"><Select id="global-enrichment-cap" value={draft.cap_mode} onChange={e => set('cap_mode', e.target.value as EnrichmentSettings['cap_mode'])}>
        <option value="proportional">Proporzionale: numero di subunità</option><option value="fixed">Numero fisso</option><option value="off">Disattivato</option>
      </Select></Field>
      {draft.cap_mode === 'fixed' && <Field label="Numero massimo" htmlFor="global-enrichment-number"><Input id="global-enrichment-number" type="number" required min={1} max={1000} value={draft.cap_number} onChange={e => set('cap_number', e.target.valueAsNumber)} /></Field>}
      <Field label="Utilità minima (0–1)" htmlFor="enrichment-utility"><Input id="enrichment-utility" type="number" required min={0} max={1} step={0.05} value={draft.utility_threshold} onChange={e => set('utility_threshold', e.target.valueAsNumber)} /></Field>
      <Field label="Modello decisionale" htmlFor="enrichment-decision-model"><Input id="enrichment-decision-model" required value={draft.decision_model} onChange={e => set('decision_model', e.target.value)} /></Field>
      <Field label="Nome credenziale" htmlFor="enrichment-decision-credential"><Input id="enrichment-decision-credential" required value={draft.decision_credential} onChange={e => set('decision_credential', e.target.value)} /></Field>
      <Field label="Endpoint Decision API" htmlFor="enrichment-decision-url"><Input id="enrichment-decision-url" required type="url" value={draft.decision_base_url} onChange={e => set('decision_base_url', e.target.value)} /></Field>
      <Button className="self-start" disabled={save.isPending}>Salva arricchimento</Button>
      {save.isSuccess && <p role="status" className="text-sm">Impostazioni salvate.</p>}
      {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    </form>
  </Section>
}
