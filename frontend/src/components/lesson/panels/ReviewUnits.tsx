import { Check, Circle, CircleAlert, CircleDashed, ShieldCheck, MoreHorizontal, Tags, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Schemas } from '@/api/client'
import { IconButton } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'
import { cn } from '@/lib/utils'
import { issueOf, type IssueItem } from '../reviewIssues'

export type ReviewUnit = Schemas['ReviewUnit']
const labels: Record<ReviewUnit['state'], string> = { ok: 'Senza problemi', issues: 'Con issue', changed: 'Testo cambiato', never: 'Mai verificata', excluded: 'Esclusa dal classificatore', failed: 'Verifica fallita' }
const icon = { ok: Check, issues: CircleAlert, changed: CircleDashed, never: Circle, excluded: Circle, failed: CircleAlert }
export function ReviewUnits({ units, busy, running, selectedUnit, items, onVerify, onReverify, onClassifier, renderIssues }: {
  units: ReviewUnit[]; busy: boolean; running: string[]; selectedUnit?: string | null; items: IssueItem[]
  onVerify: (unit: string) => void; onReverify: (unit: string) => void; onClassifier: () => void; renderIssues: (unit: string) => ReactNode
}) {
  const [expansion, setExpansion] = useState(() => ({ selectedUnit, ids: new Set<string>(selectedUnit == null ? [] : [selectedUnit]) }))
  if (expansion.selectedUnit !== selectedUnit) setExpansion({ selectedUnit, ids: new Set([...expansion.ids, ...(selectedUnit == null ? [] : [selectedUnit])]) })
  return <ul aria-label="Unità della verifica" className="flex flex-col">
    {units.map(unit => {
      const Icon = icon[unit.state]
      const verifying = running.includes(unit.unit_id)
      const needsReview = ['never', 'changed', 'failed'].includes(unit.state)
      const open = expansion.ids.has(unit.unit_id)
      const pending = items.filter(item => issueOf(item).unit_id === unit.unit_id && (!item.decision || item.needs_reconfirmation))
      return <li key={unit.unit_id} data-testid={`review-unit-${unit.state}`} data-unit={unit.unit_id} className={cn('group/review-unit border-t py-2', unit.state === 'excluded' && 'text-muted-foreground')}>
        <div className="flex items-center gap-1">
          <IconButton label={`${open ? 'Chiudi' : 'Apri'} le issue dell’unità ${unit.unit_id}`} icon={ChevronRight} className={cn('size-7 min-w-7 [&_svg]:size-4', open && '[&_svg]:rotate-90')} onClick={() => setExpansion(old => { const ids = new Set(old.ids); if (open) ids.delete(unit.unit_id); else ids.add(unit.unit_id); return { ...old, ids } })} />
          <Icon aria-label={labels[unit.state]} className={cn('size-4 shrink-0', unit.state === 'ok' ? 'text-success' : unit.state === 'issues' ? 'text-warning' : unit.state === 'failed' ? 'text-danger' : 'text-muted-foreground', unit.state === 'changed' && 'review-unit-changed')} />
          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => window.dispatchEvent(new CustomEvent(EDITOR_SCROLL_EVENT, { detail: { unitId: unit.unit_id } }))}>
            <span className="block truncate text-body"><b className="mr-2 tabular-nums">{unit.unit_id}</b>{unit.title}</span>
            <span className="block text-meta text-muted-foreground">{verifying ? 'Verifico…' : labels[unit.state]}</span>
          </button>
          <span className="inline-flex gap-1" aria-label={`${pending.length} issue da decidere`}>{pending.map(item => <span key={issueOf(item).id} aria-label={`Gravità ${({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issueOf(item).severity] ?? issueOf(item).severity}`} className={cn('size-1.5 rounded-full', issueOf(item).severity === 'high' ? 'bg-danger' : issueOf(item).severity === 'medium' ? 'bg-warning' : 'bg-muted-foreground')} />)}</span>
          {unit.state === 'excluded' ? <IconButton label="Apri il Classificatore" icon={Tags} onClick={onClassifier} /> : <div className="flex items-center gap-1 md:opacity-0 md:group-hover/review-unit:opacity-100 md:group-focus-within/review-unit:opacity-100">
            <IconButton label={`Verifica l'unità ${unit.unit_id}`} icon={ShieldCheck} unavailable={busy || verifying ? 'Lavorazione in corso' : !needsReview ? 'Unità già verificata' : !unit.unit_id ? 'Unità non ritrovata' : null} onClick={() => onVerify(unit.unit_id)} />
            <LinkMenuButton label={`Azioni sull’unità ${unit.unit_id}`} icon={MoreHorizontal} unavailable={busy || !unit.unit_id ? 'Unità non disponibile' : undefined} items={[{ label: 'Riesegui l’unità', onSelect: () => onReverify(unit.unit_id) }]} />
          </div>}
        </div>
        {open && <div className="ml-7" data-testid="review-issue-group">{renderIssues(unit.unit_id)}</div>}
      </li>
    })}
  </ul>
}
