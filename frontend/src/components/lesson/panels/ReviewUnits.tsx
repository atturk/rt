import { Check, Circle, CircleAlert, CircleDashed, ShieldCheck, MoreHorizontal } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { LinkMenuButton } from '@/components/ui/menu'
import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'
import { cn } from '@/lib/utils'

export type ReviewUnit = Schemas['ReviewUnit']
const labels: Record<ReviewUnit['state'], string> = { ok: 'Senza problemi', issues: 'Con issue', changed: 'Testo cambiato', never: 'Mai verificata', excluded: 'Esclusa', failed: 'Verifica fallita' }
const icon = { ok: Check, issues: CircleAlert, changed: CircleDashed, never: Circle, excluded: Circle, failed: CircleAlert }
export function ReviewUnits({ units, busy, running, onVerify, onReverify, onFilter }: {
  units: ReviewUnit[]; busy: boolean; running: string[]
  onVerify: (unit: string) => void; onReverify: (unit: string) => void; onFilter: (unit: string) => void
}) {
  return <ul aria-label="Unità della verifica" className="flex flex-col">
    {units.map(unit => {
      const Icon = icon[unit.state]
      const verifying = running.includes(unit.unit_id)
      const needsReview = ['never', 'changed', 'failed'].includes(unit.state)
      return <li key={unit.unit_id} data-testid={`review-unit-${unit.state}`} data-unit={unit.unit_id} className="flex items-center gap-2 border-t py-3">
        <Icon aria-label={labels[unit.state]} className={cn('size-4 shrink-0', unit.state === 'ok' ? 'text-success' : unit.state === 'issues' ? 'text-warning' : unit.state === 'failed' ? 'text-danger' : 'text-muted-foreground', unit.state === 'changed' && 'review-unit-changed')} />
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => window.dispatchEvent(new CustomEvent(EDITOR_SCROLL_EVENT, { detail: { unitId: unit.unit_id } }))}>
          <span className="block truncate text-body"><b className="mr-2 tabular-nums">{unit.unit_id}</b>{unit.title}</span>
          <span className="block text-meta text-muted-foreground">{verifying ? 'Verifico…' : <>{labels[unit.state]}{unit.reviewed_at && ` · ${new Date(unit.reviewed_at).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`}{unit.model && ` · ${unit.model}`}</>}</span>
        </button>
        {unit.issues_total > 0 && <Button size="sm" variant="ghost" aria-label={`${unit.issues_total} issue nell’unità ${unit.unit_id}`} onClick={() => onFilter(unit.unit_id)}>{unit.issues_total}</Button>}
        {!verifying && needsReview && <Button size="sm" variant="outline" disabled={busy} aria-label={`Verifica l'unità ${unit.unit_id}`} onClick={() => onVerify(unit.unit_id)}><ShieldCheck />Verifica</Button>}
        {!verifying && ['ok', 'issues'].includes(unit.state) && <LinkMenuButton label={`Azioni sull’unità ${unit.unit_id}`} icon={MoreHorizontal} unavailable={busy ? 'Verifica in corso' : undefined} items={[{ label: 'Verifica di nuovo', onSelect: () => onReverify(unit.unit_id) }]} />}
      </li>
    })}
  </ul>
}
