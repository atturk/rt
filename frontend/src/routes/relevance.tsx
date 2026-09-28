import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { useLesson, useLessonDocument } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'

type Category = NonNullable<Schemas['UnitRelevanceOverride']['category']>
const labels: Record<Category, string> = {
  didactic: 'Contenuto didattico',
  organizational: 'Informazioni organizzative',
  no_content: 'Assenza di contenuto didattico',
}

function UnitRow({ lessonId, unit, timestamp }: { lessonId: number; unit: Schemas['UnitRelevanceItem']; timestamp?: string | null }) {
  const client = useQueryClient()
  const [choice, setChoice] = useState<Category>(unit.effective)
  const update = useMutation({
    mutationFn: (category: Category | null) => unwrap(api.PUT('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
      params: { path: { lesson_id: lessonId, unit_id: unit.unit_id } }, body: { category },
    })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['relevance', lessonId] })
      void client.invalidateQueries({ queryKey: ['lesson', lessonId] })
    },
  })
  return <Card className="p-4" data-testid="relevance-unit">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold">{unit.unit_id} · {unit.title} {timestamp && <span className="ml-2 rounded bg-accent px-1.5 py-0.5 text-xs text-accent-foreground">{timestamp}</span>}</h2>
      <Link className="text-xs underline" to={`/lezioni/${lessonId}#unit-${unit.unit_id}`}>Vai all’unità</Link>
    </div>
    <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{unit.content}</p>
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <Badge tone={unit.prediction && unit.prediction !== 'didactic' ? 'warning' : 'neutral'}>JEV: {unit.prediction ? labels[unit.prediction] : 'nessuna classificazione'}</Badge>
      {unit.confidence != null && <span>Confidenza: {Math.round(unit.confidence * 100)}%</span>}
      <span>Effettiva: {labels[unit.effective]}</span>
      {unit.override && <Badge tone="success">Corretta dall’utente{unit.corrected_at ? ` · ${new Date(unit.corrected_at).toLocaleString('it-IT')}` : ''}</Badge>}
      {unit.stale && <Badge tone="warning">Da rivalutare: contenuto o modello cambiato</Badge>}
      {unit.prior_override && <Badge tone="warning">Correzione precedente da riconfermare: {labels[unit.prior_override]}</Badge>}
    </div>
    {unit.error && <Alert tone="warning">Classificazione non riuscita: {unit.error}. L’unità passa comunque.</Alert>}
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <label className="text-sm">Classificazione corretta
        <Select className="mt-1" value={choice} onChange={(e) => setChoice(e.target.value as Category)}>
          {Object.entries(labels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </Select>
      </label>
      <Button size="sm" disabled={update.isPending} onClick={() => update.mutate(choice)}>Applica correzione</Button>
      {unit.override && <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => update.mutate(null)}>Ripristina JEV</Button>}
    </div>
    {update.isError && <Alert tone="danger">{errorMessage(update.error)}</Alert>}
  </Card>
}

export function RelevancePage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  const data = useQuery({ queryKey: ['relevance', id], queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/relevance', { params: { path: { lesson_id: id } } })) })
  const [filter, setFilter] = useState<'all' | 'excluded'>('excluded')
  const units = (data.data?.units ?? []).filter((u) => filter === 'all' || u.prediction === 'organizational' || u.prediction === 'no_content' || u.effective !== 'didactic')
  const checked = data.data?.units.filter((u) => u.override != null) ?? []
  const omissions = checked.filter((u) => u.prediction && u.prediction !== 'didactic' && u.override === 'didactic').length
  return <section className="flex flex-col gap-4">
    <Link to={`/lezioni/${id}`} className="text-xs underline">← Torna alla lezione</Link>
    <h1 className="text-xl font-bold">Verifica JEV · {lesson.data?.titolo ?? `Lezione ${id}`}</h1>
    {data.isError && <Alert tone="danger">{errorMessage(data.error)}</Alert>}
    {data.isPending && <p>Carico le classificazioni…</p>}
    {data.data && <>
      <Alert tone={data.data.mode === 'active' ? 'warning' : 'neutral'}>
        {data.data.mode === 'active' ? 'Filtro attivo: le unità non didattiche vengono escluse dalle nuove review e domande Recall.' :
          data.data.mode === 'shadow' ? 'Modalità ombra: JEV classifica, ma tutte le unità proseguono verso review e Recall.' :
            'JEV disattivato: tutte le unità proseguono; le classificazioni precedenti restano consultabili.'}
      </Alert>
      <p className="text-sm text-muted-foreground">Controlla un campione, in particolare introduzioni e unità miste. Le correzioni si applicano alle esecuzioni successive; la bozza originale resta visibile.</p>
      <Card className="p-3 text-sm">
        <strong>Campione controllato: {checked.length} / {data.data.units.length}</strong>
        <span className="ml-3">Omissioni didattiche individuate: {omissions}</span>
        {checked.length > 0 && <table className="mt-2 w-full text-left text-xs"><caption className="text-left font-medium">JEV → correzione umana</caption>
          <thead><tr><th>Classe JEV</th>{Object.values(labels).map((label) => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{(Object.keys(labels) as Category[]).map((predicted) => <tr key={predicted}><th>{labels[predicted]}</th>
            {(Object.keys(labels) as Category[]).map((corrected) => <td key={corrected}>{checked.filter((u) => u.prediction === predicted && u.override === corrected).length}</td>)}
          </tr>)}</tbody>
        </table>}
      </Card>
      <div className="flex gap-2"><Button size="sm" variant={filter === 'excluded' ? 'default' : 'outline'} onClick={() => setFilter('excluded')}>Possibili omissioni</Button>
        <Button size="sm" variant={filter === 'all' ? 'default' : 'outline'} onClick={() => setFilter('all')}>Tutte le unità ({data.data.units.length})</Button></div>
      {units.map((unit) => <UnitRow key={`${unit.unit_id}:${unit.effective}:${unit.override ?? ''}`} lessonId={id} unit={unit} timestamp={document.data?.sections.find((s) => s.unit_id === unit.unit_id)?.start_formatted} />)}
      {units.length === 0 && <p className="text-sm text-muted-foreground">Nessuna unità in questa vista.</p>}
    </>}
  </section>
}
