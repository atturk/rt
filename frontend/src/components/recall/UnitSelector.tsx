import { errorMessage } from '@/api/client'
import { useRecallUnits, useSelectRecallUnits, type RecallUnit } from '@/api/recall'
import { Alert } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

const CATEGORY: Record<string, string> = { organizational: 'organizzativa', no_content: 'senza contenuto', didactic: 'didattica' }
const LEVEL_TONE = ['bg-muted text-muted-foreground', 'bg-accent text-accent-foreground', 'bg-success-soft text-success']

function score(value: number | null | undefined) {
  return value == null ? '' : value.toLocaleString('it-IT', { maximumFractionDigits: 1, minimumFractionDigits: 1 })
}

function describe(unit: RecallUnit) {
  if (unit.error) return 'Classificazione non riuscita'
  if (!unit.category) return 'Non classificata'
  const parts = [`Categoria: ${CATEGORY[unit.category] ?? unit.category}`]
  if (unit.score != null) parts.push(`score ${score(unit.score)}`)
  if (unit.level != null) parts.push(`livello ${unit.level}`)
  if (unit.confidence != null) parts.push(`confidenza ${Math.round(unit.confidence * 100)}%`)
  return parts.join(' · ')
}

function UnitRow({ unit, onToggle }: { unit: RecallUnit; onToggle: () => void }) {
  const dimmed = !unit.suggested
  return (
    <li>
      <label
        className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted"
        title={describe(unit)}
        data-testid="recall-unit"
        data-unit-id={unit.unit_id}
      >
        <input type="checkbox" checked={unit.selected} onChange={onToggle} className="shrink-0" />
        <span className="shrink-0 font-mono text-xs text-muted-foreground">{unit.unit_id}</span>
        <span className={cn('min-w-0 flex-1 truncate', dimmed && 'text-muted-foreground')}>{unit.title}</span>
        {unit.category && unit.category !== 'didactic' && (
          <span className="shrink-0 text-[11px] text-muted-foreground">{CATEGORY[unit.category]}</span>
        )}
        {unit.score != null && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{score(unit.score)}</span>}
        {unit.level != null && (
          <span className={cn('shrink-0 rounded px-1 text-[11px] font-medium tabular-nums', LEVEL_TONE[unit.level])} aria-label={`livello ${unit.level}`}>
            L{unit.level}
          </span>
        )}
      </label>
    </li>
  )
}

/**
 * Le unità che il recaller riceve: di predefinito solo le rilevanti per il classificatore,
 * con score e livello. Chiuso mostra solo quante sono selezionate.
 */
export function UnitSelector({ lessonId }: { lessonId: number }) {
  const units = useRecallUnits(lessonId)
  const select = useSelectRecallUnits(lessonId)
  if (units.isPending) return null
  if (units.isError) return <Alert tone="danger">{errorMessage(units.error)}</Alert>
  const { units: rows, custom, classifier } = units.data
  const selected = rows.filter((u) => u.selected)
  const save = (ids: string[] | null) => select.mutate(ids)
  const toggle = (unit: RecallUnit) =>
    save(rows.filter((u) => (u.unit_id === unit.unit_id ? !u.selected : u.selected)).map((u) => u.unit_id))

  return (
    <details className="group rounded-lg border px-3 py-2" data-testid="unit-selector">
      <summary className="cursor-pointer select-none text-sm">
        <span className="font-medium">Unità per il recaller</span>{' '}
        <span className="text-muted-foreground" data-testid="unit-selector-count">
          {selected.length} di {rows.length} selezionate · {custom ? 'scelta tua' : 'solo rilevanti'}
        </span>
      </summary>
      <div className="mt-2 flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <button type="button" className="underline-offset-4 hover:underline disabled:opacity-50" onClick={() => save(null)} disabled={!custom}>
            Solo rilevanti
          </button>
          <button type="button" className="underline-offset-4 hover:underline" onClick={() => save(rows.map((u) => u.unit_id))}>
            Tutte
          </button>
          <button type="button" className="underline-offset-4 hover:underline" onClick={() => save([])}>
            Nessuna
          </button>
          <span className="ml-auto text-muted-foreground">
            {classifier === 'disabled'
              ? 'Classificatore non configurato: di predefinito tutte le unità.'
              : 'Score 0–2 del classificatore · livello L0 nessuna domanda, L1 una, L2 più domande'}
          </span>
        </div>
        <ul className="grid max-h-72 gap-x-4 overflow-y-auto sm:grid-cols-2" aria-label="Unità della lezione">
          {rows.map((u) => (
            <UnitRow key={u.unit_id} unit={u} onToggle={() => toggle(u)} />
          ))}
        </ul>
        {select.isError && <Alert tone="danger">{errorMessage(select.error)}</Alert>}
      </div>
    </details>
  )
}
