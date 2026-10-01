import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { useLesson, useLessonDocument } from '@/api/hooks'
import { useRunClassifier } from '@/api/relevance'
import { RUN_ALL, RUN_NEW } from '@/lib/classification'
import { JobProgress } from '@/components/JobProgress'
import { SectionLabelsCard } from '@/components/recall/SectionLabels'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'

type Category = NonNullable<Schemas['UnitRelevanceOverride']['category']>
type Unit = Schemas['UnitRelevanceItem']
const labels: Record<Category, string> = {
  didactic: 'Contenuto didattico',
  organizational: 'Informazioni organizzative',
  no_content: 'Assenza di contenuto didattico',
}
const CATEGORIES = Object.keys(labels) as Category[]

/** Da dove viene l'etichetta effettiva di un'unità, detto in una parola. */
function origin(unit: Unit): { text: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
  if (unit.override) return { text: 'Corretta da te', tone: 'success' }
  if (unit.error) return { text: 'Non riuscita', tone: 'danger' }
  if (unit.stale) return { text: 'Da rivalutare', tone: 'warning' }
  if (!unit.prediction) return { text: 'Da classificare', tone: 'warning' }
  return { text: 'Classificatore', tone: 'neutral' }
}

/** Score 0–2 del classificatore (contenuto assente, limitato, ricco): il colore lo dice subito. */
function scoreOf(unit: Unit): number | null {
  const score = (unit.answer as { score?: unknown } | null | undefined)?.score
  return typeof score === 'number' && Number.isFinite(score) ? score : null
}
function scoreTone(score: number | null): 'neutral' | 'success' | 'warning' | 'danger' {
  if (score == null) return 'neutral'
  return score < 0.5 ? 'danger' : score < 1.5 ? 'warning' : 'success'
}
const formatScore = (score: number) => score.toLocaleString('it-IT', { maximumFractionDigits: 1, minimumFractionDigits: 1 })

/** Etichetta restituita dal classificatore (es. "Contenuto limitato") con lo score. */
function LabelBadge({ unit }: { unit: Unit }) {
  if (!unit.label && unit.prediction == null) return null
  const score = scoreOf(unit)
  return <Badge tone={scoreTone(score)} data-testid="relevance-label" title={score != null ? `Score ${formatScore(score)} su 2` : undefined}>
    {unit.label ?? labels[unit.prediction as Category]}{score != null ? ` · ${formatScore(score)}` : ''}
  </Badge>
}

/** Stato della classificazione sulla lezione, con i pulsanti per eseguirla (job unit_relevance,
 * come 'rt relevance'). A job finito la pagina rilegge le classificazioni. */
function StatusCard({ lessonId, overview }: { lessonId: number; overview: Schemas['UnitRelevanceOverview'] }) {
  const run = useRunClassifier(lessonId)
  const disabled = overview.mode === 'disabled'
  const s = overview.summary
  const total = s?.total ?? overview.units.length
  const status = !s || (s.classified === 0 && s.errors === 0)
    ? { tone: 'warning' as const, text: s && s.stale > 0 ? 'Da rieseguire: testo o configurazione cambiati' : 'Mai eseguito su questa lezione' }
    : s.classified === total ? { tone: 'success' as const, text: 'Eseguito su tutte le unità' }
      : { tone: 'warning' as const, text: `Eseguito su ${s.classified} / ${total} unità` }
  const counts = CATEGORIES.map((c) => [c, overview.units.filter((u) => u.effective === c).length] as const)
  // Etichette del classificatore (es. Contenuto assente/limitato/ricco), dalla più povera di contenuto.
  const byLabel = Object.entries(s?.by_label ?? {}).map(([label, n]) => {
    const scores = overview.units.filter((u) => (u.label ?? u.prediction) === label).map(scoreOf).filter((x): x is number => x != null)
    return { label, n, score: scores.length ? Math.min(...scores) : null }
  }).sort((a, b) => (a.score ?? 3) - (b.score ?? 3))
  const details = s ? [s.errors > 0 && `${s.errors} non riuscite (passano come didattiche)`, s.stale > 0 && `${s.stale} da rivalutare`,
    s.missing > 0 && s.classified > 0 && `${s.missing} mai classificate`, s.corrected > 0 && `${s.corrected} corrette da te`].filter(Boolean) : []
  const ran = !!s && (s.classified > 0 || s.errors > 0)
  return <Card className="flex flex-col gap-3 p-4 text-sm" data-testid="relevance-summary">
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={status.tone} className="text-xs">{status.text}</Badge>
      {s?.last_run_at && <span className="text-xs text-muted-foreground">Ultima esecuzione: {new Date(s.last_run_at).toLocaleString('it-IT')}
        {s.model ? ` · ${s.model}` : ''}</span>}
    </div>
    {byLabel.length > 0 && <div className="flex flex-col gap-1">
      <span className="text-xs font-medium">Esito del classificatore</span>
      <ul className="flex flex-wrap gap-2 text-xs" aria-label="Unità per etichetta del classificatore" data-testid="relevance-by-label">
        {byLabel.map(({ label, n, score }) => <li key={label}><Badge tone={scoreTone(score)}>{label}: {n}</Badge></li>)}
      </ul>
    </div>}
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium">Effetto su review e recall</span>
      <ul className="flex flex-wrap gap-2 text-xs" aria-label="Unità per etichetta">
        {counts.map(([c, n]) => <li key={c}><Badge tone={c !== 'didactic' && n > 0 ? 'warning' : 'neutral'}>{labels[c]}: {n}</Badge></li>)}
      </ul>
      <p className="text-xs text-muted-foreground">
        Le etichette del classificatore diventano «didattica», «organizzativa» o «assenza di contenuto» secondo la mappatura in
        Impostazioni › Modelli › Classificatore.{' '}
        {overview.mode === 'active'
          ? 'Lo score (0–2) orienta il recaller: dove il contenuto è scarso chiede meno domande (L0 nessuna, L1 una, L2 più domande).'
          : 'In modalità ombra lo score è solo informativo: il recaller non lo riceve.'}
      </p>
    </div>
    {details.length > 0 && <p className="text-xs text-muted-foreground">{details.join(' · ')}</p>}
    <div className="flex flex-wrap items-center gap-2" data-testid="relevance-run">
      <Button size="sm" disabled={disabled || run.busy} title={RUN_NEW.title} onClick={() => run.start.mutate(false)}>
        {ran ? RUN_NEW.label : RUN_NEW.first}</Button>
      <Button size="sm" variant="outline" disabled={disabled || run.busy} title={RUN_ALL.title} onClick={() => run.start.mutate(true)}>{RUN_ALL.label}</Button>
      {disabled && <span className="text-xs text-muted-foreground">Il classificatore di rilevanza è disattivato: attivalo in <Link className="underline" to="/impostazioni/modelli">Impostazioni</Link>.</span>}
    </div>
    {!disabled && <ul className="list-disc pl-5 text-xs text-muted-foreground">
      <li><strong>{ran ? RUN_NEW.label : RUN_NEW.first}</strong>: {RUN_NEW.title}</li>
      <li><strong>{RUN_ALL.label}</strong>: {RUN_ALL.title}</li>
    </ul>}
    {run.start.isError && <Alert tone="danger">{errorMessage(run.start.error)}</Alert>}
    {run.jobId && <JobProgress jobId={run.jobId} label="Etichette del classificatore" onFinished={run.finished} />}
  </Card>
}

/** Una riga dell'elenco: titolo ed etichetta subito visibili e modificabili; il testo completo
 * e la risposta del classificatore si aprono con il titolo. */
function UnitRow({ lessonId, unit, timestamp }: { lessonId: number; unit: Unit; timestamp?: string | null }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const update = useMutation({
    mutationFn: (category: Category | null) => unwrap(api.PUT('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
      params: { path: { lesson_id: lessonId, unit_id: unit.unit_id } }, body: { category },
    })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['relevance', lessonId] })
      void client.invalidateQueries({ queryKey: ['lesson', lessonId] })
    },
  })
  // Scegliere di nuovo l'etichetta del classificatore toglie la correzione.
  const choose = (category: Category) => update.mutate(category === unit.prediction ? null : category)
  const from = origin(unit)
  const panel = `relevance-unit-${unit.unit_id}`
  return <li className="border-b last:border-b-0" data-testid="relevance-unit">
    <div className="flex flex-wrap items-center gap-2 py-2">
      <button type="button" className="flex min-w-0 flex-1 items-baseline gap-2 text-left" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}>
        <span aria-hidden className="w-3 text-muted-foreground">{open ? '▾' : '▸'}</span>
        <span className="font-medium">{unit.unit_id} · {unit.title}</span>
        {timestamp && <span className="rounded bg-accent px-1.5 py-0.5 text-xs text-accent-foreground">{timestamp}</span>}
      </button>
      <LabelBadge unit={unit} />
      <Badge tone={from.tone}>{from.text}</Badge>
      <Select className="w-auto" aria-label={`Etichetta di ${unit.unit_id}`} value={unit.effective} disabled={update.isPending}
        onChange={(e) => choose(e.target.value as Category)}>
        {CATEGORIES.map((value) => <option value={value} key={value}>{labels[value]}</option>)}
      </Select>
    </div>
    {update.isError && <Alert tone="danger">{errorMessage(update.error)}</Alert>}
    {open && <div id={panel} className="mb-3 ml-5 flex flex-col gap-2 text-sm">
      <p className="whitespace-pre-wrap">{unit.content}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>Classificatore sulla bozza: {unit.prediction ? labels[unit.prediction] : 'nessuna classificazione'}</span>
        {unit.label && <span>Etichetta restituita: {unit.label}</span>}
        <span>Orientamento recall sul testo corretto: {unit.recall_assessment?.level != null ? `livello ${unit.recall_assessment.level}` : 'neutro'}</span>
        {unit.confidence != null && <span>{unit.answer?.type === 'noul' ? 'Probabilità' : 'Confidenza'}: {Math.round(unit.confidence * 100)}%</span>}
        {unit.answer?.probabilities != null && typeof unit.answer.probabilities === 'object' &&
          <span data-testid="relevance-probabilities">Probabilità: {Object.entries(unit.answer.probabilities as Record<string, number>)
            .map(([key, value]) => `${key} ${Math.round(value * 100)}%`).join(' · ')}</span>}
        {unit.override && unit.corrected_at && <span>Corretta il {new Date(unit.corrected_at).toLocaleString('it-IT')}</span>}
        {unit.prior_override && <span>Correzione precedente da riconfermare: {labels[unit.prior_override]}</span>}
      </div>
      {unit.error && <Alert tone="warning">Classificazione non riuscita: {unit.error}. L’unità passa comunque.</Alert>}
      <div className="flex flex-wrap gap-3 text-xs">
        <Link className="underline" to={`/lezioni/${lessonId}#unit-${unit.unit_id}`}>Vai all’unità nella lezione</Link>
        {unit.override && <button type="button" className="underline" disabled={update.isPending} onClick={() => update.mutate(null)}>Ripristina il classificatore</button>}
      </div>
    </div>}
  </li>
}

type Filter = 'all' | 'excluded' | 'check'
const FILTERS: Record<Filter, { label: string; match: (u: Unit) => boolean }> = {
  all: { label: 'Tutte', match: () => true },
  excluded: { label: 'Non didattiche', match: (u) => u.effective !== 'didactic' },
  check: { label: 'Da controllare', match: (u) => !u.override && (!!u.error || u.stale || !u.prediction || !!u.prior_override) },
}

export function RelevancePage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  const data = useQuery({ queryKey: ['relevance', id], queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/relevance', { params: { path: { lesson_id: id } } })) })
  const [filter, setFilter] = useState<Filter>('all')
  const all = data.data?.units ?? []
  const units = all.filter(FILTERS[filter].match)
  return <section className="flex flex-col gap-4">
    <Link to={`/lezioni/${id}`} className="text-xs underline">← Torna alla lezione</Link>
    <div>
      <h1 className="text-xl font-bold">Classificatore · {lesson.data?.titolo ?? `Lezione ${id}`}</h1>
      <p className="text-sm text-muted-foreground">Ogni unità riceve un’etichetta; le unità non didattiche possono essere escluse da review e domande Recall. Puoi cambiare qualsiasi etichetta a mano.</p>
    </div>
    {data.isError && <Alert tone="danger">{errorMessage(data.error)}</Alert>}
    {data.isPending && <p>Carico le classificazioni…</p>}
    {data.data && <>
      <Alert tone={data.data.mode === 'active' ? 'warning' : 'neutral'}>
        {data.data.mode === 'active' ? 'Filtro attivo: le unità non didattiche vengono escluse dalle nuove review e domande Recall.' :
          data.data.mode === 'shadow' ? 'Modalità ombra: il classificatore etichetta, ma tutte le unità proseguono verso review e Recall.' :
            'Classificatore disattivato: tutte le unità proseguono; le etichette precedenti restano consultabili.'}
      </Alert>
      <StatusCard lessonId={id} overview={data.data} />
      <Card className="p-4">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtra le unità">
          {(Object.keys(FILTERS) as Filter[]).map((key) => <Button key={key} size="sm" variant={filter === key ? 'default' : 'outline'} aria-pressed={filter === key}
            onClick={() => setFilter(key)}>{FILTERS[key].label} ({all.filter(FILTERS[key].match).length})</Button>)}
        </div>
        <ul className="mt-2" aria-label="Unità della lezione">
          {units.map((unit) => <UnitRow key={unit.unit_id} lessonId={id} unit={unit} timestamp={document.data?.sections.find((s) => s.unit_id === unit.unit_id)?.start_formatted} />)}
        </ul>
        {units.length === 0 && <p className="mt-2 text-sm text-muted-foreground">Nessuna unità in questa vista.</p>}
      </Card>
      <SectionLabelsCard lessonId={id} />
    </>}
  </section>
}
