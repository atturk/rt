import type { Schemas } from '@/api/client'
import { Card } from '@/components/ui/card'
import { formatCost } from '@/lib/format'

const JOB_NAMES: Record<string, string> = {
  outline: 'Scaletta',
  rewrite: 'Rielaborazione',
  review: 'Revisione',
  recall: 'Recall',
  image_description: 'Descrizione immagini',
  image_unit_judge: 'Posizione immagini',
}

type JobCost = { total_calls?: number; total_cost?: number; has_unknown_cost?: boolean }

/** Costi per fase LLM, dallo stesso report di 'rt cost'. */
export function CostPanel({ lesson }: { lesson: Schemas['LessonDetail'] }) {
  const cost = lesson.cost as { total_estimated_cost_usd?: number; total_calls?: number; has_unknown_cost?: boolean; by_job?: Record<string, JobCost> } | null
  const byJob = Object.entries(cost?.by_job ?? {})
  return (
    <Card className="p-4" data-testid="cost-panel">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-bold">Costi</h2>
        <span className="text-sm font-semibold tabular-nums">{formatCost(cost?.total_estimated_cost_usd ?? lesson.cost_usd)}</span>
      </div>
      {byJob.length > 0 ? (
        <table className="mt-2 w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="font-medium">Fase</th>
              <th className="text-right font-medium">Chiamate</th>
              <th className="text-right font-medium">Costo</th>
            </tr>
          </thead>
          <tbody>
            {byJob.map(([job, data]) => (
              <tr key={job} className="border-t">
                <td className="py-1">{JOB_NAMES[job] ?? job}</td>
                <td className="text-right tabular-nums">{data.total_calls ?? 0}</td>
                <td className="text-right tabular-nums">
                  {formatCost(data.total_cost)}
                  {data.has_unknown_cost ? '*' : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">Nessuna chiamata LLM registrata.</p>
      )}
      {cost?.has_unknown_cost && <p className="mt-2 text-[11px] text-muted-foreground">* alcune chiamate senza prezzo noto</p>}
    </Card>
  )
}
