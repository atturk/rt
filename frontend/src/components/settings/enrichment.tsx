import { useState } from 'react'
import { errorMessage } from '@/api/client'
import { useEnrichmentSettings, useSaveEnrichmentSettings, type EnrichmentSettings } from '@/api/enrichment'
import type { Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { SettingsGroup, SettingsRow, SettingsSelect as Select } from './ui'
import { useAutoSave } from './useAutoSave'

export function EnrichmentSettingsSection({ decisions = false }: { settings: Settings; decisions?: boolean }) {
  const query = useEnrichmentSettings()
  const save = useSaveEnrichmentSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return query.data ? <EnrichmentForm settings={query.data} decisions={decisions} save={save} /> : <p className="text-body text-muted-foreground">Carico l’arricchimento…</p>
}

function EnrichmentForm({ settings, decisions, save }: { settings: EnrichmentSettings; decisions: boolean; save: ReturnType<typeof useSaveEnrichmentSettings> }) {
  const [draftEdit, setDraftEdit] = useState<{ base: EnrichmentSettings; value: EnrichmentSettings } | null>(null)
  const draft = draftEdit && JSON.stringify(draftEdit.base) === JSON.stringify(settings) ? draftEdit.value : settings

  const valid =
    (draft.cap_mode !== 'fixed' || (Number.isFinite(draft.cap_number) && draft.cap_number >= 1 && draft.cap_number <= 1000)) &&
    Number.isFinite(draft.utility_threshold) &&
    draft.utility_threshold >= 0 &&
    draft.utility_threshold <= 1

  const autoSave = useAutoSave(save, draft, {
    delay: 600,
    enabled: valid,
    initial: settings,
    serialize: (val) => ({ ...val, automatic: val.mode === 'automatic' }),
  })

  function changeCapMode(cap_mode: EnrichmentSettings['cap_mode']) {
    const next = { ...draft, cap_mode }
    setDraftEdit({ base: settings, value: next })
    autoSave.saveNow(next)
  }

  return (
    <SettingsGroup
      id={decisions ? 'arricchimento-decisionale' : 'arricchimento'}
      title={decisions ? 'Modello decisionale dell’arricchimento' : 'Arricchimento'}
    >
      <SettingsRow
        label="Tetto globale"
        htmlFor="global-enrichment-cap"
        info="Limita il numero massimo di elementi di arricchimento generati per ogni lezione."
        control={
          <Select id="global-enrichment-cap" className="w-full @sm:w-60" value={draft.cap_mode} onChange={e => changeCapMode(e.target.value as EnrichmentSettings['cap_mode'])}>
            <option value="proportional">Proporzionale: numero di subunità</option>
            <option value="fixed">Numero fisso</option>
            <option value="off">Disattivato</option>
          </Select>
        }
      />
      {draft.cap_mode === 'fixed' && (
        <SettingsRow
          label="Numero massimo"
          htmlFor="global-enrichment-number"
          status={autoSave}
          control={
            <Input
              id="global-enrichment-number"
              type="number"
              required
              min={1}
              max={1000}
              className="w-full @sm:w-24"
              value={Number.isFinite(draft.cap_number) ? draft.cap_number : ''}
              onChange={e => setDraftEdit({ base: settings, value: { ...draft, cap_number: e.target.valueAsNumber } })}
              onBlur={autoSave.flush}
            />
          }
        />
      )}
      <SettingsRow
        label="Utilità minima (0–1)"
        htmlFor="enrichment-utility"
        info="Soglia minima stimata perché una proposta di arricchimento venga accettata."
        status={autoSave}
        control={
          <Input
            id="enrichment-utility"
            type="number"
            required
            min={0}
            max={1}
            step={0.05}
            className="w-full @sm:w-24"
            value={Number.isFinite(draft.utility_threshold) ? draft.utility_threshold : ''}
            onChange={e => setDraftEdit({ base: settings, value: { ...draft, utility_threshold: e.target.valueAsNumber } })}
            onBlur={autoSave.flush}
          />
        }
      />
    </SettingsGroup>
  )
}
