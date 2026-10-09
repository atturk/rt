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
import { Field, Section, SettingsSelect as Select } from './common'

type Config = components['schemas']['ClassifierConfig']
type Job = components['schemas']['ClassifierJobConfig']
const jobs: [string, string, string, boolean][] = [
  ['relevance', 'Rilevanza', 'Esclude le subunità non didattiche', true],
  ['question_types', 'Tipo di domanda', 'Consiglia il tipo per subunità', false],
  ['section_labels', 'Esercizi e casi clinici', 'Individua esercizi e contenuti clinici', false],
  ['prefilter', 'Prefiltro errori', 'Salta la revisione delle subunità corrette', true],
  ['drift', 'Deriva dal trascritto', 'Segnala contenuto assente dal trascritto', true],
  ['enrichment', 'Arricchimento', 'Valuta infografiche e visualizzazioni', false],
  ['images', 'Immagini', 'Assegna le immagini alle unità', false],
]
export function ClassifierSettingsSection() {
  const query = useQuery({ queryKey: ['classifier-settings'], queryFn: () => unwrap(api.GET('/api/v1/settings/classifier')) })
  return query.data ? <ClassifierForm key={JSON.stringify(query.data)} initial={query.data} /> : query.isError ? <Alert tone="danger">{errorMessage(query.error)}</Alert> : null
}
function ClassifierForm({ initial }: { initial: Config }) {
  const [draft, setDraft] = useState(initial)
  const [expanded, setExpanded] = useState<string | null>(null)
  const settings = useSettings()
  const client = useQueryClient()
  const save = useMutation({ mutationFn: () => unwrap(api.PUT('/api/v1/settings/classifier', { body: draft })), onSuccess: saved => { client.setQueryData(['classifier-settings'], saved); void client.invalidateQueries({ queryKey: ['decision-model'] }) } })
  const decisions = useQuery({ queryKey: ['decision-model'], queryFn: () => unwrap(api.GET('/api/v1/settings/decision-model')) })
  const probe = useMutation({ mutationFn: async (name?: string) => {
    const selected = name ? jobs.filter(job => job[0] === name) : jobs.filter(job => draft.jobs?.[job[0]]?.mode !== 'off')
    const seen = new Set<string>()
    for (const [job] of selected) {
      const own = draft.jobs?.[job]
      const model = own?.model || draft.model
      const credential = own?.credential || draft.credential
      const base_url = own?.base_url || draft.base_url
      const request_type = job === 'relevance' ? decisions.data?.relevance_decision.type ?? 'score' : job === 'prefilter' ? decisions.data?.prefilter_decision.type ?? 'choice' : job === 'enrichment' || job === 'drift' ? 'noul' : 'choice'
      const key = JSON.stringify([model, credential, base_url, request_type])
      if (seen.has(key)) continue
      seen.add(key)
      await unwrap(api.POST('/api/v1/settings/classifier/probe', { body: { mode: 'manual', model, credential, base_url, timeout_seconds: draft.timeout_seconds, request_type } }))
    }
  } })
  const update = (name: string, change: Partial<Job>) => setDraft(old => ({ ...old, jobs: { ...old.jobs, [name]: { mode: "off", ...old.jobs?.[name], ...change } } }))
  const credentials = settings.data?.credentials ?? []
  return <Section id="classificatore" title="Classificatore">
    <div className="grid gap-2 sm:grid-cols-2">
      <Field label="Modello condiviso" htmlFor="classifier-model"><Input id="classifier-model" value={draft.model ?? ''} onChange={e => setDraft({ ...draft, model: e.target.value })} /></Field>
      <Field label="Connessione" htmlFor="classifier-credential"><Select id="classifier-credential" value={draft.credential ?? ''} onChange={e => setDraft({ ...draft, credential: e.target.value })}>{credentials.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field>
      <Field label="Endpoint Decision API" htmlFor="classifier-url"><Input id="classifier-url" value={draft.base_url ?? ''} onChange={e => setDraft({ ...draft, base_url: e.target.value || null })} /></Field>
      <Field label="Timeout (secondi)" htmlFor="classifier-timeout"><Input id="classifier-timeout" type="number" min={1} max={300} value={draft.timeout_seconds ?? 30} onChange={e => setDraft({ ...draft, timeout_seconds: e.target.valueAsNumber })} /></Field>
    </div>
    {jobs.map(([name, label, description, observe]) => <div key={name} className="border-t py-3">
      <div className="flex items-center gap-2"><div className="flex-1"><p className="text-body">{label}</p><p className="text-meta text-muted-foreground">{description}</p></div>
        <Select aria-label={`Modalità ${label}`} value={draft.jobs?.[name]?.mode ?? 'off'} onChange={e => update(name, { mode: e.target.value as Job['mode'] })}><option value="off">Spento</option><option value="manual">Manuale</option>{observe && <option value="observe">In osservazione</option>}{name !== 'images' && <option value="pipeline">In pipeline</option>}</Select>
        <IconButton icon={MoreHorizontal} label={`Modello proprio ${label}`} onClick={() => setExpanded(expanded === name ? null : name)} />
      </div>
      {expanded === name && <div className="grid gap-2 pt-2 sm:grid-cols-2"><Field label="Modello proprio" htmlFor={`cls-model-${name}`}><Input id={`cls-model-${name}`} value={draft.jobs?.[name]?.model ?? ''} onChange={e => update(name, { model: e.target.value || null })} /></Field><Field label="Connessione propria" htmlFor={`cls-credential-${name}`}><Select id={`cls-credential-${name}`} value={draft.jobs?.[name]?.credential ?? ''} onChange={e => update(name, { credential: e.target.value || null })}><option value="">Condivisa</option>{credentials.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field><Field label="Endpoint proprio" htmlFor={`cls-url-${name}`}><Input id={`cls-url-${name}`} value={draft.jobs?.[name]?.base_url ?? ''} onChange={e => update(name, { base_url: e.target.value || null })} /></Field><Button variant="outline" disabled={probe.isPending} onClick={() => probe.mutate(name)}>Prova modello proprio</Button></div>}
    </div>)}
    <div className="flex gap-2"><Button variant="outline" disabled={probe.isPending} onClick={() => probe.mutate(undefined)}>Prova connessione</Button><Button disabled={save.isPending} onClick={() => save.mutate()}>Salva classificatore</Button></div>
    {(save.isError || probe.isError) && <Alert tone="danger">{errorMessage(save.error ?? probe.error)}</Alert>}
    {(save.isSuccess || probe.isSuccess) && <p role="status" className="text-meta text-success">{save.isSuccess ? 'Salvato.' : 'Connessione verificata.'}</p>}
  </Section>
}
