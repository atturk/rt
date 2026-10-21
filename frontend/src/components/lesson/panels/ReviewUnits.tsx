import { Check, Circle, CircleAlert, CircleDashed, ShieldCheck, MoreHorizontal, Tags, ChevronRight, Clock3, LoaderCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Schemas } from '@/api/client'
import { IconButton } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'
import { cn } from '@/lib/utils'
import { MathText } from '@/components/MathText'
import { issueOf, type IssueItem } from '../reviewIssues'

export type ReviewUnit = Schemas['ReviewUnit']
const labels: Record<ReviewUnit['state'], string> = { ok: 'Senza problemi', issues: 'Con issue', changed: 'Testo cambiato', never: 'Mai verificata', excluded: 'Esclusa dal classificatore', failed: 'Verifica fallita' }
const icon = { ok: Check, issues: CircleAlert, changed: CircleDashed, never: Circle, excluded: Circle, failed: CircleAlert }
export function ReviewUnits({ units, busy, running, queued, missing, selectedUnit, items, onVerify, onReverify, onBypass, onClassifier, renderIssues }: {
  units: ReviewUnit[]; busy: boolean; running: string[]; queued: string[]; missing: string[]; selectedUnit?: string | null; items: IssueItem[]
  onVerify: (unit: string) => void; onReverify: (unit: string) => void; onBypass: (unit: string, excluded: boolean) => void; onClassifier: () => void; renderIssues: (unit: string) => ReactNode
}) {
  const [expansion, setExpansion] = useState(() => ({ selectedUnit, ids: new Set<string>(selectedUnit == null ? [] : [selectedUnit]) }))
  if (expansion.selectedUnit !== selectedUnit) setExpansion({ selectedUnit, ids: new Set([...expansion.ids, ...(selectedUnit == null ? [] : [selectedUnit])]) })
  return <ul aria-label="Unità della verifica" className="flex flex-col">
    {units.map(unit => {
      const verifying = running.includes(unit.unit_id)
      const waiting = queued.includes(unit.unit_id)
      const Icon = verifying ? LoaderCircle : waiting ? Clock3 : icon[unit.state]
      const unavailable = missing.includes(unit.unit_id)
      const needsReview = ['never', 'changed', 'failed'].includes(unit.state)
      const open = expansion.ids.has(unit.unit_id)
      const pending = items.filter(item => issueOf(item).unit_id === unit.unit_id && (!item.decision || item.needs_reconfirmation))
      return <li key={unit.unit_id} data-testid={`review-unit-${unit.state}`} data-unit={unit.unit_id} className={cn('group/review-unit border-t py-2', unit.state === 'excluded' && 'text-muted-foreground')}>
        <div className="flex items-center gap-1">
          <IconButton label={`${open ? 'Chiudi' : 'Apri'} le issue dell’unità ${unit.unit_id}`} icon={ChevronRight} className={cn('size-7 min-w-7 [&_svg]:size-4', open && '[&_svg]:rotate-90')} onClick={() => setExpansion(old => { const ids = new Set(old.ids); if (open) ids.delete(unit.unit_id); else ids.add(unit.unit_id); return { ...old, ids } })} />
          <Icon role="img" aria-label={verifying ? 'In corso' : waiting ? 'In coda' : labels[unit.state]} className={cn('size-4 shrink-0', verifying || waiting ? 'text-muted-foreground' : unit.state === 'ok' ? 'text-success' : unit.state === 'issues' ? 'text-warning' : unit.state === 'failed' ? 'text-danger' : 'text-muted-foreground', verifying && 'animate-spin', !verifying && !waiting && unit.state === 'changed' && 'review-unit-changed')} />
          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => window.dispatchEvent(new CustomEvent(EDITOR_SCROLL_EVENT, { detail: { unitId: unit.unit_id } }))}>
            <span className="block truncate text-body"><b className="mr-2 tabular-nums">{unit.unit_id}</b><MathText text={unit.title ?? ''} /></span>
            <span className="block text-meta text-muted-foreground">{verifying ? 'In corso' : waiting ? 'In coda' : labels[unit.state]}</span>
          </button>
          <span className="inline-flex gap-1" role="group" aria-label={`${pending.length} issue da decidere`}>{pending.map(item => <span key={issueOf(item).id} role="img" aria-label={`Gravità ${({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issueOf(item).severity] ?? issueOf(item).severity}`} className={cn('size-1.5 rounded-full', issueOf(item).severity === 'high' ? 'bg-danger' : issueOf(item).severity === 'medium' ? 'bg-warning' : 'bg-muted-foreground')} />)}</span>
          {unit.state === 'excluded' && <IconButton label="Apri il Classificatore" icon={Tags} onClick={onClassifier} />}
          <div className="flex items-center gap-1 md:opacity-0 md:group-hover/review-unit:opacity-100 md:group-focus-within/review-unit:opacity-100">
            {unit.state !== 'excluded' && <IconButton label={`Verifica l'unità ${unit.unit_id}`} icon={ShieldCheck} unavailable={unavailable ? 'Unità non ritrovata' : busy || verifying || waiting ? 'Lavorazione in corso' : !needsReview ? 'Unità già verificata' : !unit.unit_id ? 'Unità non ritrovata' : null} onClick={() => onVerify(unit.unit_id)} />}
            <LinkMenuButton label={`Azioni sull’unità ${unit.unit_id}`} icon={MoreHorizontal} unavailable={busy || unavailable || !unit.unit_id ? 'Unità non disponibile' : undefined} items={[
              ...(unit.state === 'excluded' ? [] : [{ label: 'Riesegui l’unità', unavailable: unit.state === 'never' && !unit.reviewed_at ? 'Unità mai verificata' : null, onSelect: () => onReverify(unit.unit_id) }]),
              { label: 'Esegui senza classificatore', onSelect: () => onBypass(unit.unit_id, unit.state === 'excluded') },
            ]} />
          </div>
        </div>
        {open && <div className="ml-7" data-testid="review-issue-group">{renderIssues(unit.unit_id)}</div>}
      </li>
    })}
  </ul>
}
