import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, LayoutGrid, Table2 } from 'lucide-react'
import { useId, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import type { LessonGroup, SortDir } from '@/lib/lessonView'
import { cn } from '@/lib/utils'

/**
 * Barra e intestazioni degli elenchi di lezioni delle pagine Recall, Review e Immagini
 * (LessonBrowser, RecallOverview). La pagina Lezioni del design 4.2 sta in
 * components/lessons/LessonsView.tsx.
 */

export function SortHeader<K extends string>({ label, sortKey, prefs, onSort, className }: {
  label: string
  sortKey: K
  prefs: { sort: K; dir: SortDir }
  onSort: (key: K) => void
  className?: string
}) {
  const active = prefs.sort === sortKey
  const Icon = !active ? ArrowUpDown : prefs.dir === 'asc' ? ArrowUp : ArrowDown
  return (
    <th scope="col" aria-sort={active ? (prefs.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className={cn('px-3 py-2 font-medium', className)}>
      <button type="button" onClick={() => onSort(sortKey)}
        className={cn('-mx-1 inline-flex items-center gap-1 rounded px-1 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring', active && 'text-foreground')}>
        {label}
        <Icon className={cn('size-3.5', !active && 'opacity-40')} aria-hidden />
      </button>
    </th>
  )
}

export function GroupToggle({ group, expanded, onToggle, controls }: { group: LessonGroup; expanded: boolean; onToggle: () => void; controls: string }) {
  return (
    <button type="button" aria-expanded={expanded} aria-controls={controls} onClick={onToggle} data-testid="lesson-group-toggle"
      className="inline-flex items-center gap-2 rounded-md py-1 pr-2 text-sm font-semibold hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-ring">
      <ChevronRight className={cn('size-4 transition-transform motion-reduce:transition-none', expanded && 'rotate-90')} aria-hidden />
      {group.label}
      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
        {group.lessons.length}
        <span className="sr-only"> {group.lessons.length === 1 ? 'lezione' : 'lezioni'}</span>
      </span>
    </button>
  )
}

function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string
  value: T
  options: { value: T; label: string; icon: ReactNode }[]
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex h-9 rounded-md border border-input bg-card p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} title={o.label} onClick={() => onChange(o.value)}
          className={cn(
            'inline-flex items-center gap-1.5 rounded px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring [&_svg]:size-4',
            value === o.value && 'bg-muted text-foreground',
          )}>
          {o.icon}
          <span className="max-sm:sr-only">{o.label}</span>
        </button>
      ))}
    </div>
  )
}

/** Riga sopra un elenco di lezioni (dashboard, Recall, Review, Immagini): ricerca, quante
 * lezioni, azzera filtri, raggruppa, ordina e vista. */
export function ViewToolbar<S extends string, G extends string>({ shown, total, filtered, onReset, search, prefs, onChange, sortLabels, groupLabels, defaultDir }: {
  shown: number
  total: number
  filtered: boolean
  onReset: () => void
  /** Campo "Cerca" a sinistra del numero di lezioni. */
  search?: { id: string; value: string; onChange: (value: string) => void }
  prefs: { view: 'schede' | 'tabella'; sort: S; dir: SortDir; group: G }
  onChange: (patch: { view?: 'schede' | 'tabella'; sort?: S; dir?: SortDir; group?: G }) => void
  sortLabels: Record<S, string>
  /** Senza, niente "Raggruppa per". */
  groupLabels?: Record<G, string>
  defaultDir: Record<S, SortDir>
}) {
  const id = useId()
  const DirIcon = prefs.dir === 'asc' ? ArrowUp : ArrowDown
  const dirText = prefs.sort === 'data'
    ? prefs.dir === 'desc' ? 'dalla più recente' : 'dalla meno recente'
    : prefs.dir === 'asc' ? 'crescente' : 'decrescente'
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-wrap items-end gap-3">
      {search && (
        <form className="flex flex-col gap-1" role="search" aria-label="Filtra le lezioni" onSubmit={(e) => e.preventDefault()}>
          <Label htmlFor={search.id} className="text-xs">Cerca</Label>
          <Input id={search.id} type="search" className="w-52" placeholder="Titolo, materia, docente, data…"
            value={search.value} onChange={(e) => search.onChange(e.target.value)} />
        </form>
      )}
      <p className="pb-2 text-sm text-muted-foreground" role="status" data-testid="lesson-count">
        {filtered ? (
          <>
            <strong className="font-semibold text-foreground tabular-nums">{shown}</strong> di {total} lezioni
            <Button variant="link" size="sm" className="ml-1 h-auto px-1" onClick={onReset}>Azzera filtri</Button>
          </>
        ) : (
          <><strong className="font-semibold text-foreground tabular-nums">{total}</strong> {total === 1 ? 'lezione' : 'lezioni'}</>
        )}
      </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {groupLabels && (
          <div className="flex flex-col gap-1">
            <Label htmlFor={`${id}-group`} className="text-xs">Raggruppa per</Label>
            <Select id={`${id}-group`} className="w-32" value={prefs.group} onChange={(e) => onChange({ group: e.target.value as G })}>
              {(Object.keys(groupLabels) as G[]).map((g) => <option key={g} value={g}>{groupLabels[g]}</option>)}
            </Select>
          </div>
        )}
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-sort`} className="text-xs">Ordina per</Label>
          <div className="flex">
            <Select id={`${id}-sort`} className="w-40 rounded-r-none" value={prefs.sort}
              onChange={(e) => { const sort = e.target.value as S; onChange({ sort, dir: defaultDir[sort] }) }}>
              {(Object.keys(sortLabels) as S[]).map((s) => <option key={s} value={s}>{sortLabels[s]}</option>)}
            </Select>
            <Button variant="outline" size="icon" className="-ml-px rounded-l-none" aria-label={`Ordine ${dirText}: inverti`} title={`Ordine ${dirText}`}
              onClick={() => onChange({ dir: (prefs.dir === 'asc' ? 'desc' : 'asc') as SortDir })}>
              <DirIcon />
            </Button>
          </div>
        </div>
        <Segmented label="Vista" value={prefs.view} onChange={(view) => onChange({ view })} options={[
          { value: 'schede', label: 'Schede', icon: <LayoutGrid aria-hidden /> },
          { value: 'tabella', label: 'Tabella', icon: <Table2 aria-hidden /> },
        ]} />
      </div>
    </div>
  )
}
