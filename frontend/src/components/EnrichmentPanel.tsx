import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { errorMessage, type Schemas } from '@/api/client'
import { useEnrichment, useEnrichmentActions, useBatchEnrichment } from '@/api/enrichment'
import { EnrichmentCard } from '@/components/lesson/Enrichment'
import { kindLabel } from '@/lib/enrichment'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import type { Lesson } from '@/lib/format'

export function AnalyzeLesson({ id, ready }: { id: number; ready: boolean }) {
  const { analyze, refresh } = useEnrichmentActions(id)
  return <div className="flex flex-col gap-2">
    <Button variant="outline" size="sm" disabled={!ready || analyze.isPending} onClick={() => analyze.mutate()}>Analizza arricchimento</Button>
    {analyze.data && <JobProgress jobId={analyze.data.job_id} label="Analisi delle idee" onFinished={refresh} />}
    {analyze.isError && <Alert tone="danger">{errorMessage(analyze.error)}</Alert>}
  </div>
}

export function AnalyzeGroup({ lessons }: { lessons: Lesson[] }) {
  const batch = useBatchEnrichment()
  return <div className="my-2 text-sm font-normal">
    <Button size="sm" variant="outline" disabled={batch.isPending} onClick={() => batch.mutate(lessons.map(l => l.id))}>Analizza il gruppo ({lessons.length})</Button>
    {batch.data && <p role="status" className="mt-2 text-xs">{batch.data.queued} job accodati · {batch.data.existing} già attivi · {batch.data.skipped.length} lezioni saltate.</p>}
    {batch.data?.skipped.length !== 0 && batch.data && <ul className="mt-2 text-xs text-muted-foreground">
      {batch.data.skipped.map(id => <li key={id}>Lezione {id}: {batch.data?.skipped_reasons?.[id] ?? 'Non disponibile'}</li>)}</ul>}
    {batch.data && <details className="mt-2"><summary>Stato dei job</summary>{batch.data.jobs.map(j => <JobProgress key={j.job_id} jobId={j.job_id} label={`Lezione ${j.lesson_id}`} />)}</details>}
    {batch.isError && <Alert tone="danger">{errorMessage(batch.error)}</Alert>}
  </div>
}

export function EnrichmentPanel({ lessonId }: { lessonId: number }) {
  const query = useEnrichment(lessonId)
  const { generate, edit, cap, refresh } = useEnrichmentActions(lessonId)
  const [params, setParams] = useSearchParams()
  const editId = params.get('edit')
  const current = query.data?.elements.find(e => e.id === editId)
  const [unit, setUnit] = useState('')
  const [kind, setKind] = useState<Schemas['Element']['kind']>('visualization')
  const [mode, setMode] = useState<Schemas['Element']['mode']>('interactive')
  const [prompt, setPrompt] = useState('')
  const [title, setTitle] = useState('Elemento grafico')
  const [description, setDescription] = useState('Generazione manuale')
  const [capMode, setCapMode] = useState<Schemas['Cap']['mode']>('inherit')
  const [capNumber, setCapNumber] = useState(5)
  const [showIgnored, setShowIgnored] = useState(false)
  const currentId = current?.id
  useEffect(() => {
    if (current) {
      setUnit(current.unit_id); setKind(current.kind); setMode(current.mode ?? 'static')
      setPrompt(current.prompt); setTitle(current.title); setDescription(current.description)
    }
    // Polling must not overwrite a user's unsaved prompt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId])
  const savedCapMode = query.data?.cap.mode
  const savedCapNumber = query.data?.cap.number
  useEffect(() => { setCapMode(savedCapMode ?? 'inherit'); setCapNumber(savedCapNumber ?? 5) }, [savedCapMode, savedCapNumber])
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (current) {
      await edit.mutateAsync({ id: current.id, title, description, prompt, kind, mode: kind === 'infographic' ? 'static' : mode })
      await generate.mutateAsync({ element_id: current.id })
    } else {
      await generate.mutateAsync({ unit_id: unit || query.data?.units[0]?.id, kind, title, description, prompt, mode })
    }
  }
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  if (!query.data) return <p>Carico le idee…</p>
  const visible = query.data.elements.filter(e => e.status !== 'suppressed' && (showIgnored || e.status !== 'dismissed'))
  return <>
    <Card className="flex flex-col gap-3 p-5">
      <h2 className="font-bold">Suggerimenti utili, senza riempire ogni unità</h2>
      <AnalyzeLesson id={lessonId} ready />
      <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); cap.mutate({ mode: capMode, number: capNumber }) }}>
        <div><Label htmlFor="lesson-cap">Tetto dei suggerimenti</Label><Select id="lesson-cap" value={capMode} onChange={e => setCapMode(e.target.value as typeof capMode)}>
          <option value="inherit">Usa impostazione globale</option><option value="off">Disattivato</option><option value="fixed">Numero fisso</option><option value="proportional">Proporzionale alle subunità</option>
        </Select></div>
        {capMode === 'fixed' && <Input aria-label="Numero massimo" className="w-24" type="number" min={1} max={1000} required value={capNumber} onChange={e => setCapNumber(e.target.valueAsNumber)} />}
        <Button variant="outline" disabled={cap.isPending}>Salva tetto</Button>
      </form>
      <p className="text-xs text-muted-foreground">Massimo effettivo: {query.data.effective_limit ?? 'nessun tetto'}. È un limite, non un obiettivo; la generazione manuale è libera.</p>
      {cap.isError && <Alert tone="danger">{errorMessage(cap.error)}</Alert>}
    </Card>
    <Card id="generazione" className="flex scroll-mt-6 flex-col gap-3 p-5">
      <h2 className="font-bold">{current ? 'Modifica e rigenera' : 'Generazione manuale'}</h2>
      <form onSubmit={e => { void submit(e).catch(() => undefined) }} className="flex flex-col gap-3">
        <Label htmlFor="enrich-unit">Subunità</Label><Select id="enrich-unit" value={unit || query.data.units[0]?.id} disabled={Boolean(current)} onChange={e => setUnit(e.target.value)}>
          {query.data.units.map(u => <option key={u.id} value={u.id}>{u.id} · {u.title}</option>)}
        </Select>
        <Label htmlFor="enrich-kind">Tipo di elemento</Label><Select id="enrich-kind" value={kind} onChange={e => setKind(e.target.value as typeof kind)}>
          <option value="visualization">Visualizzazione HTML/SVG: grafici, matrici, diagrammi, simulazioni</option><option value="infographic">Infografica</option>
        </Select>
        {kind === 'visualization' && <><Label htmlFor="enrich-mode">Modalità</Label><Select id="enrich-mode" value={mode} onChange={e => setMode(e.target.value as typeof mode)}>
          <option value="interactive">Interattiva</option><option value="static">Statica</option></Select></>}
        <Label htmlFor="enrich-title">Titolo</Label><Input id="enrich-title" required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} />
        <Label htmlFor="enrich-prompt">Prompt</Label><textarea id="enrich-prompt" required maxLength={12000} rows={6} className="rounded border bg-background p-3 text-sm"
          placeholder="Es. rappresenta la matrice dei vincoli, evidenziando la relazione tra righe, variabili ed equazioni…" value={prompt} onChange={e => setPrompt(e.target.value)} />
        <p className="text-xs text-muted-foreground">Il generatore riceve soltanto il testo della subunità selezionata e questo prompt.</p>
        <div className="flex gap-2"><Button disabled={generate.isPending || edit.isPending || !prompt.trim()}>{current ? 'Salva e rigenera' : 'Genera e aggiungi'}</Button>
          {current && <Button type="button" variant="outline" onClick={() => { setParams({}); setPrompt(''); setTitle('Elemento grafico') }}>Nuovo elemento</Button>}</div>
      </form>
      {(generate.isError || edit.isError) && <Alert tone="danger">{errorMessage(generate.error ?? edit.error)}</Alert>}
      {generate.data && <JobProgress jobId={generate.data.job_id} label="Generazione" onFinished={refresh} />}
    </Card>
    <Card className="flex flex-col gap-2 p-5">
      <h2 className="font-bold">Idee e contenuti della lezione</h2>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={showIgnored} onChange={e => setShowIgnored(e.target.checked)} />Mostra anche le idee ignorate</label>
      {visible.length === 0 && <p className="text-sm text-muted-foreground">Nessuna idea ancora. Avvia l’analisi oppure genera un elemento manualmente.</p>}
      {visible.map(e => <EnrichmentCard key={e.id} element={e} lessonId={lessonId} manage />)}
      <p className="sr-only">Tipi supportati: {kindLabel('visualization')}, {kindLabel('infographic')}.</p>
    </Card>
  </>
}
