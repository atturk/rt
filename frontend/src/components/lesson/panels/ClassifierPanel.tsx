import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { useRunClassifier } from '@/api/relevance'
import { RUN_ALL, RUN_NEW } from '@/lib/classification'
import { JobProgress } from '@/components/JobProgress'
import { SectionLabelsCard } from '@/components/recall/SectionLabels'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'

type Category = NonNullable<Schemas['UnitRelevanceOverride']['category']>
type Unit = Schemas['UnitRelevanceItem']

const labels: Record<Category, string> = {
  didactic: 'Contenuto didattico',
  organizational: 'Informazioni organizzative',
  no_content: 'Assenza di contenuto didattico',
}
const CATEGORIES = Object.keys(labels) as Category[]

function scoreOf(unit: Unit): number | null {
  const score = (unit.answer as { score?: unknown } | null | undefined)?.score
  return typeof score === 'number' && Number.isFinite(score) ? score : null
}

function scoreTone(score: number | null): 'neutral' | 'success' | 'warning' | 'danger' {
  if (score == null) return 'neutral'
  return score < 0.5 ? 'danger' : score < 1.5 ? 'warning' : 'success'
}

const formatScore = (score: number) =>
  score.toLocaleString('it-IT', { maximumFractionDigits: 1, minimumFractionDigits: 1 })

type Filter = 'all' | 'excluded' | 'check'

const FILTERS: Record<Filter, { label: string; match: (u: Unit) => boolean }> = {
  all: { label: 'Tutte', match: () => true },
  excluded: { label: 'Non didattiche', match: (u) => u.effective !== 'didactic' },
  check: {
    label: 'Da controllare',
    match: (u) => !u.override && (!!u.error || u.stale || !u.prediction || !!u.prior_override),
  },
}

export function ClassifierPanel({ lessonId }: { lessonId?: number }) {
  const params = useParams()
  const id = lessonId ?? Number(params.lessonId)
  const client = useQueryClient()

  const data = useQuery({
    queryKey: ['relevance', id],
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/relevance', { params: { path: { lesson_id: id } } })),
    enabled: Number.isFinite(id),
  })

  const run = useRunClassifier(id)
  const [filter, setFilter] = useState<Filter>('all')

  const update = useMutation({
    mutationFn: ({ unitId, category }: { unitId: string; category: Category | null }) =>
      unwrap(
        api.PUT('/api/v1/lessons/{lesson_id}/relevance/{unit_id}', {
          params: { path: { lesson_id: id, unit_id: unitId } },
          body: { category },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['relevance', id] })
      void client.invalidateQueries({ queryKey: ['lesson', id] })
    },
  })

  if (!Number.isFinite(id)) return null
  if (data.isPending) return <p className="text-meta text-muted-foreground">Carico le classificazioni…</p>
  if (data.isError) return <Alert tone="danger">{errorMessage(data.error)}</Alert>
  if (!data.data) return null

  const overview = data.data
  const disabled = overview.mode === 'disabled'
  const s = overview.summary
  const all = overview.units
  const total = s?.total ?? all.length
  const ran = !!s && (s.classified > 0 || s.errors > 0)
  const units = all.filter(FILTERS[filter].match)

  const choose = (unit: Unit, category: Category) => {
    update.mutate({ unitId: unit.unit_id, category: category === unit.prediction ? null : category })
  }

  return (
    <div className="flex flex-col gap-3.5 text-body" data-testid="classifier-panel">
      {/* Scheda stato e avvio classificazione */}
      <Card className="flex flex-col gap-2.5 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-body font-semibold">
            {s ? `${s.classified} di ${total} unità classificate` : `${total} unità`}
          </span>
          <Badge tone={overview.mode === 'active' ? 'neutral' : 'warning'}>
            {overview.mode === 'active' ? 'attivo' : overview.mode}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="default"
            disabled={disabled || run.busy}
            title={RUN_NEW.title}
            onClick={() => run.start.mutate(false)}
          >
            {ran ? 'Classifica le nuove' : 'Classifica la lezione'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || run.busy}
            title={RUN_ALL.title}
            onClick={() => run.start.mutate(true)}
          >
            Riclassifica tutte
          </Button>
        </div>

        {disabled && (
          <p className="text-meta text-muted-foreground">
            Il classificatore di rilevanza è disattivato nelle impostazioni.
          </p>
        )}
        {run.start.isError && <Alert tone="danger">{errorMessage(run.start.error)}</Alert>}
        {run.jobId && <JobProgress jobId={run.jobId} label="Etichette del classificatore" onFinished={run.finished} />}
      </Card>

      {/* Filtri */}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtra le unità">
        {(Object.keys(FILTERS) as Filter[]).map((key) => {
          const count = all.filter(FILTERS[key].match).length
          const isActive = filter === key
          return (
            <button
              key={key}
              type="button"
              aria-pressed={isActive}
              className={cn(
                'inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-meta font-medium transition-colors',
                isActive ? 'bg-primary text-primary-foreground font-semibold' : 'bg-muted text-foreground hover:bg-muted/80',
              )}
              onClick={() => setFilter(key)}
            >
              {FILTERS[key].label} {count}
            </button>
          )
        })}
      </div>

      {/* Elenco unità */}
      <ul className="flex flex-col gap-1.5" aria-label="Unità della lezione">
        {units.map((unit) => {
          const score = scoreOf(unit)
          const isNonDidactic = unit.effective !== 'didactic'
          return (
            <li
              key={unit.unit_id}
              className={cn(
                'flex flex-col gap-1.5 rounded-lg border p-2.5 transition-colors',
                isNonDidactic ? 'bg-muted/70' : 'bg-card',
              )}
              data-testid="relevance-unit"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 flex-1 truncate text-body font-medium">
                  <span className="mr-1.5 font-mono text-meta text-muted-foreground">{unit.unit_id}</span>
                  {unit.title}
                </span>
                <Badge tone={scoreTone(score)} title={score != null ? `Score ${formatScore(score)} su 2` : 'Score'}>
                  {score != null ? formatScore(score) : '—'}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Select
                  className="h-7 w-auto py-0 text-meta"
                  aria-label={`Etichetta di ${unit.unit_id}`}
                  value={unit.effective}
                  disabled={update.isPending}
                  onChange={(e) => choose(unit, e.target.value as Category)}
                >
                  {CATEGORIES.map((val) => (
                    <option key={val} value={val}>
                      {labels[val]}
                    </option>
                  ))}
                </Select>

                {unit.override ? (
                  <span className="text-meta text-muted-foreground">
                    corretta da te ·{' '}
                    <button
                      type="button"
                      className="text-meta text-link hover:underline"
                      disabled={update.isPending}
                      onClick={() => update.mutate({ unitId: unit.unit_id, category: null })}
                    >
                      ripristina
                    </button>
                  </span>
                ) : unit.stale ? (
                  <span className="text-meta text-warning">da rivalutare</span>
                ) : unit.error ? (
                  <span className="text-meta text-danger">errore</span>
                ) : !unit.prediction ? (
                  <span className="text-meta text-warning">da classificare</span>
                ) : null}
              </div>
            </li>
          )
        })}
      </ul>

      {units.length === 0 && <p className="text-meta text-muted-foreground">Nessuna unità in questa vista.</p>}

      {update.isError && <Alert tone="danger">{errorMessage(update.error)}</Alert>}

      <hr className="border-border" />

      {/* Sezioni da cui nascono casi ed esercizi */}
      <SectionLabelsCard lessonId={id} />
    </div>
  )
}
