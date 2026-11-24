import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import { api, unwrap, errorMessage } from '@/api/client'
import type { components } from '@/api/schema'
import { useSettings } from '@/api/settings'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Alert } from '@/components/ui/alert'
import { AutoSaveStatus, SettingsGroup, SettingsRow, SettingsSelect as Select } from './ui'
import { useAutoSave } from './useAutoSave'

type Config = components['schemas']['ClassifierConfig']
type Job = components['schemas']['ClassifierJobConfig']
const jobs: [string, string, string, boolean][] = [
  ['relevance', 'Rilevanza', 'Esclude le subunità non didattiche', true],
  ['question_types', 'Tipo di domanda', 'Consiglia il tipo per subunità', false],
  ['section_labels', 'Tipi di domanda personalizzati', 'Individua le sezioni adatte ai tipi di Impostazioni › Domande', false],
  ['prefilter', 'Prefiltro errori', 'Salta la revisione delle subunità corrette', true],
  ['drift', 'Deriva dal trascritto', 'Segnala contenuto assente dal trascritto', true],
  ['enrichment', 'Arricchimento', 'Valuta infografiche e visualizzazioni', false],
  ['images', 'Immagini', 'Assegna le immagini alle unità', false],
]
export function ClassifierSettingsSection() {
  const query = useQuery({ queryKey: ['classifier-settings'], queryFn: () => unwrap(api.GET('/api/v1/settings/classifier')) })
  return query.data ? <ClassifierForm initial={query.data} /> : query.isError ? <Alert tone="danger">{errorMessage(query.error)}</Alert> : null
}
function ClassifierForm({ initial }: { initial: Config }) {
  const [draft, setDraft] = useState(initial)
  const [expanded, setExpanded] = useState<string | null>(null)
  const settings = useSettings()
  const client = useQueryClient()
  const save = useMutation({
    mutationFn: (body: Config) => unwrap(api.PUT('/api/v1/settings/classifier', { body })),
    onSuccess: saved => {
      client.setQueryData(['classifier-settings'], saved)
      void client.invalidateQueries({ queryKey: ['decision-model'] })
    },
  })
  const autoSave = useAutoSave(save, draft, { delay: 600, initial })
  const decisions = useQuery({ queryKey: ['decision-model'], queryFn: () => unwrap(api.GET('/api/v1/settings/decision-model')) })
  const probe = useMutation({ mutationFn: async (name?: string) => {
    const selected = name ? jobs.filter(job => job[0] === name) : jobs.filter(job => draft.jobs?.[job[0]]?.mode !== 'off')
    const seen = new Set<string>()
    for (const [job] of selected) {
      const own = draft.jobs?.[job]
      const shared = own?.model || draft.model
      // Come classifier_job: senza modello proprio le immagini usano Jev 1.14.
      const model = job === 'images' && !own?.model && shared?.startsWith('typesafe/jev-1.1') ? 'typesafe/jev-1.14' : shared
      const credential = own?.credential || draft.credential
      const base_url = own?.base_url || draft.base_url
      const request_type = job === 'relevance' ? decisions.data?.relevance_decision.type ?? 'score' : job === 'prefilter' ? decisions.data?.prefilter_decision.type ?? 'choice' : job === 'enrichment' || job === 'drift' ? 'noul' : 'choice'
      const key = JSON.stringify([model, credential, base_url, request_type, job === 'images'])
      if (seen.has(key)) continue
      seen.add(key)
      const with_image = job === 'images' && ((draft.images_reader ?? 'decision') === 'decision' || draft.material_pages_reader === 'image')
      await unwrap(api.POST('/api/v1/settings/classifier/probe', { body: { mode: 'manual', model, credential, base_url, timeout_seconds: draft.timeout_seconds, request_type, with_image, threshold: own?.threshold ?? (job === 'images' ? 0.7 : 0.8) } }))
    }
  } })
  const update = (name: string, change: Partial<Job>, immediate = false) => {
    const next: Config = { ...draft, jobs: { ...draft.jobs, [name]: { mode: 'off', ...draft.jobs?.[name], ...change } } }
    setDraft(next)
    if (immediate) autoSave.saveNow(next)
  }
  const credentials = settings.data?.credentials ?? []
  return (
    <SettingsGroup id="classificatore" title="Classificatore">
      <SettingsRow
        label="Modello condiviso"
        htmlFor="classifier-model"
        control={
          <Input
            id="classifier-model"
            className="w-full @sm:w-60"
            value={draft.model ?? ''}
            onChange={e => setDraft({ ...draft, model: e.target.value })}
            onBlur={autoSave.flush}
          />
        }
      />
      <SettingsRow
        label="Connessione"
        htmlFor="classifier-credential"
        control={
          <Select
            id="classifier-credential"
            className="w-full @sm:w-60"
            value={draft.credential ?? ''}
            onChange={e => {
              const next = { ...draft, credential: e.target.value }
              setDraft(next)
              autoSave.saveNow(next)
            }}
          >
            {credentials.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
          </Select>
        }
      />
      <SettingsRow
        label="Endpoint Decision API"
        htmlFor="classifier-url"
        control={
          <Input
            id="classifier-url"
            className="w-full @sm:w-60"
            value={draft.base_url ?? ''}
            onChange={e => setDraft({ ...draft, base_url: e.target.value || null })}
            onBlur={autoSave.flush}
          />
        }
      />
      <SettingsRow
        label="Timeout (secondi)"
        htmlFor="classifier-timeout"
        control={
          <Input
            id="classifier-timeout"
            className="w-full @sm:w-24"
            type="number"
            min={1}
            max={300}
            value={draft.timeout_seconds ?? 30}
            onChange={e => setDraft({ ...draft, timeout_seconds: e.target.valueAsNumber })}
            onBlur={autoSave.flush}
          />
        }
      />
      {jobs.map(([name, label, description, observe]) => (
        <div key={name} className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-body text-foreground">{label}</p>
              <p className="text-meta text-muted-foreground">{description}</p>
            </div>
            <Select
              aria-label={`Modalità ${label}`}
              className="w-40"
              value={draft.jobs?.[name]?.mode ?? 'off'}
              onChange={e => update(name, { mode: e.target.value as Job['mode'] }, true)}
            >
              <option value="off">Spento</option>
              <option value="manual">Manuale</option>
              {observe && <option value="observe">In osservazione</option>}
              {name !== 'images' && <option value="pipeline">In pipeline</option>}
            </Select>
            {name === 'images' && (draft.jobs?.images?.mode ?? 'off') !== 'off' && (
              <>
                <Select
                  aria-label="Lettura immagini"
                  className="w-44"
                  value={draft.images_reader ?? 'decision'}
                  onChange={e => {
                    const next = { ...draft, images_reader: e.target.value as Config['images_reader'] }
                    setDraft(next)
                    autoSave.saveNow(next)
                  }}
                >
                  <option value="decision">Modello decisionale</option>
                  <option value="description">Descrittore</option>
                </Select>
                <Select
                  aria-label="Lettura pagine delle fonti"
                  className="w-40"
                  value={draft.material_pages_reader ?? 'description'}
                  onChange={e => {
                    const next = { ...draft, material_pages_reader: e.target.value as Config['material_pages_reader'] }
                    setDraft(next)
                    autoSave.saveNow(next)
                  }}
                >
                  <option value="description">Descrizione</option>
                  <option value="image">Immagine</option>
                </Select>
              </>
            )}
            <IconButton icon={MoreHorizontal} label={`Modello proprio ${label}`} onClick={() => setExpanded(expanded === name ? null : name)} />
          </div>
          {expanded === name && (
            <div className="mt-3 divide-y divide-border/60 rounded-lg border bg-background">
              <SettingsRow
                label="Modello proprio"
                htmlFor={`cls-model-${name}`}
                control={
                  <Input
                    id={`cls-model-${name}`}
                    className="w-full @sm:w-60"
                    value={draft.jobs?.[name]?.model ?? ''}
                    onChange={e => update(name, { model: e.target.value || null })}
                    onBlur={autoSave.flush}
                  />
                }
              />
              <SettingsRow
                label="Connessione propria"
                htmlFor={`cls-credential-${name}`}
                control={
                  <Select
                    id={`cls-credential-${name}`}
                    className="w-full @sm:w-60"
                    value={draft.jobs?.[name]?.credential ?? ''}
                    onChange={e => update(name, { credential: e.target.value || null }, true)}
                  >
                    <option value="">Condivisa</option>
                    {credentials.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </Select>
                }
              />
              <SettingsRow
                label="Endpoint proprio"
                htmlFor={`cls-url-${name}`}
                control={
                  <Input
                    id={`cls-url-${name}`}
                    className="w-full @sm:w-60"
                    value={draft.jobs?.[name]?.base_url ?? ''}
                    onChange={e => update(name, { base_url: e.target.value || null })}
                    onBlur={autoSave.flush}
                  />
                }
              />
              {name === 'images' && (
                <SettingsRow
                  label="Soglia assegnazione"
                  htmlFor="cls-threshold-images"
                  control={
                    <Input
                      id="cls-threshold-images"
                      className="w-full @sm:w-24"
                      type="number"
                      step={0.05}
                      min={0}
                      max={1}
                      value={draft.jobs?.[name]?.threshold ?? 0.7}
                      onChange={e => update(name, { threshold: Number.isFinite(e.target.valueAsNumber) ? e.target.valueAsNumber : undefined })}
                      onBlur={autoSave.flush}
                    />
                  }
                />
              )}
              <div className="px-4 py-2.5">
                <Button type="button" variant="outline" size="sm" disabled={probe.isPending} onClick={() => probe.mutate(name)}>
                  Prova modello proprio
                </Button>
              </div>
            </div>
          )}
        </div>
      ))}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Button type="button" variant="outline" disabled={probe.isPending} onClick={() => probe.mutate(undefined)}>
          Prova connessione
        </Button>
        <AutoSaveStatus status={autoSave.status} error={autoSave.error} onRetry={autoSave.retry} />
      </div>
      {probe.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(probe.error)}</Alert>
        </div>
      )}
      {probe.isSuccess && (
        <p role="status" className="px-4 py-2 text-meta text-success">
          Connessione verificata.
        </p>
      )}
    </SettingsGroup>
  )
}
