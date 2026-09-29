import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, Download, LayoutGrid, Table2, Trash2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'

import { api, errorMessage, unwrap } from '@/api/client'
import { PhaseBadges } from '@/components/PhaseBadges'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { PHASE_LABELS, PHASE_ORDER, STATE_LABELS, formatCost, lessonTitle, phaseTone, type Lesson } from '@/lib/format'
import {
  DEFAULT_DIR,
  GROUP_LABELS,
  SORT_LABELS,
  type LessonGroup,
  type LessonGroupBy,
  type LessonSortKey,
  type LessonViewPrefs,
  type SortDir,
} from '@/lib/lessonView'
import { optionRevealClass, useOptionKey } from '@/lib/optionKey'
import { cn } from '@/lib/utils'

/** Link con l'aspetto di un Button ghost/icon. */
const iconLink =
  'inline-flex size-9 items-center justify-center rounded-md transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring'

const stateLabel = (lesson: Lesson) => (lesson.state ? STATE_LABELS[lesson.state] ?? lesson.state : null)

/** Elimina (con conferma scritta) e, a documento valido, scarica il Markdown: compaiono con Option. */
function LessonQuickActions({ lesson, className, layout }: { lesson: Lesson; className?: string; layout: 'card' | 'row' }) {
  const optionDown = useOptionKey()
  const [confirm, setConfirm] = useState(false)
  const [typed, setTyped] = useState('')
  const client = useQueryClient()
  const deletion = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: lesson.id } } })),
    onSuccess: () => { setConfirm(false); client.invalidateQueries({ queryKey: ['lessons'] }) },
  })
  const reveal = optionRevealClass(optionDown)
  return (
    <div className={cn(layout === 'card' ? 'flex flex-col' : 'flex justify-end', className)}>
      <Button type="button" variant="ghost" size="icon" aria-label={`Elimina ${lessonTitle(lesson)}`}
        className={`${reveal} text-danger`}
        onClick={() => { setTyped(''); setConfirm(true) }}><Trash2 /></Button>
      {/* con Option: il Markdown finale (solo a build valido, non l'anteprima) */}
      {lesson.phases.build === 'VALID' && (
        <a href={`/api/v1/lessons/${lesson.id}/export?format=markdown`} download
          aria-label={`Scarica il Markdown di ${lessonTitle(lesson)}`} title="Scarica il Markdown finale"
          className={`${reveal} ${iconLink}`}>
          <Download className="size-4" aria-hidden />
        </a>
      )}
      <ConfirmDialog open={confirm} title="Elimina lezione" confirmLabel="Elimina"
        confirmDisabled={typed !== 'confermo' || deletion.isPending}
        onCancel={() => setConfirm(false)} onConfirm={() => deletion.mutate()}>
        <p>Eliminare definitivamente «{lessonTitle(lesson)}» e tutti i suoi file?</p>
        <label className="mt-3 block text-xs" htmlFor={`confirm-delete-${lesson.id}`}>Scrivi confermo</label>
        <input id={`confirm-delete-${lesson.id}`} className="mt-1 w-full rounded border p-2" value={typed} onChange={(event) => setTyped(event.target.value)} />
        {deletion.isError && <Alert tone="danger">{errorMessage(deletion.error)}</Alert>}
      </ConfirmDialog>
    </div>
  )
}

function IssuesLink({ lesson, short = false }: { lesson: Lesson; short?: boolean }) {
  if (lesson.pending_issues > 0) {
    return (
      <Link to={`/lezioni/${lesson.id}/revisione`} className="font-bold text-accent-foreground hover:underline">
        {lesson.pending_issues} {short ? <span className="sr-only">issue da valutare</span> : 'issue da valutare →'}
      </Link>
    )
  }
  return short ? <span className="text-muted-foreground" aria-label="Nessuna issue da valutare">—</span> : <span className="text-muted-foreground">Nessuna issue da valutare</span>
}

export function LessonCard({ lesson, headingLevel = 2 }: { lesson: Lesson; headingLevel?: 2 | 3 }) {
  const meta = [lesson.materia, lesson.data, stateLabel(lesson)].filter(Boolean)
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <Card className="group relative p-5" data-testid="lesson-card" data-lesson-id={lesson.id}>
      <LessonQuickActions lesson={lesson} layout="card" className="absolute right-3 top-3 gap-1" />
      <Heading className="pr-10 text-lg font-bold leading-snug tracking-tight">
        <Link to={`/lezioni/${lesson.id}`} className="hover:underline">
          {lessonTitle(lesson)}
        </Link>
      </Heading>
      <p className="mb-3 mt-1 pr-10 text-xs text-muted-foreground">{meta.join(' · ')}</p>
      <PhaseBadges phases={lesson.phases} />
      <div className="mt-4 flex flex-wrap items-baseline gap-3 border-t pt-3 text-xs">
        <span className="tabular-nums text-muted-foreground" title="Costo stimato">
          {formatCost(lesson.cost_usd)}
        </span>
        <IssuesLink lesson={lesson} />
      </div>
      {lesson.error && <p className="mt-2 text-xs text-danger">{lesson.error}</p>}
    </Card>
  )
}

const DOT_TONE = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  neutral: 'border border-muted-foreground bg-transparent',
} as const

const PHASE_STATUS_LABELS: Record<string, string> = {
  VALID: 'completata',
  PARTIAL: 'parziale',
  STALE: 'da aggiornare',
  INVALID: 'non valida',
  MISSING: 'da fare',
}

/** Le fasi in una riga di tabella: un pallino per fase, colore come i badge delle schede. */
function PhaseDots({ phases }: { phases: Record<string, string> }) {
  const names = [...PHASE_ORDER.filter((p) => p in phases), ...Object.keys(phases).filter((p) => !PHASE_ORDER.includes(p))]
  return (
    <ul className="flex items-center gap-1" aria-label="Fasi">
      {names.map((name) => {
        const status = phases[name]
        const text = `${PHASE_LABELS[name] ?? name}: ${PHASE_STATUS_LABELS[status] ?? status}`
        return (
          <li key={name} title={text} data-phase={name} data-status={status}>
            <span className={cn('block size-2.5 rounded-full', DOT_TONE[phaseTone(status)])} aria-hidden />
            <span className="sr-only">{text}</span>
          </li>
        )
      })}
    </ul>
  )
}

function SortHeader({ label, sortKey, prefs, onSort, className }: {
  label: string
  sortKey: LessonSortKey
  prefs: LessonViewPrefs
  onSort: (key: LessonSortKey) => void
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

function GroupToggle({ group, expanded, onToggle, controls }: { group: LessonGroup; expanded: boolean; onToggle: () => void; controls: string }) {
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

type ListProps = {
  groups: LessonGroup[]
  grouped: boolean
  prefs: LessonViewPrefs
  onSort: (key: LessonSortKey) => void
  onToggleGroup: (id: string) => void
}

const groupId = (prefs: LessonViewPrefs, group: LessonGroup) => `${prefs.group}:${group.key}`

function CardsView({ groups, grouped, prefs, onToggleGroup }: ListProps) {
  const base = useId()
  const grid = 'grid grid-cols-1 gap-3 lg:grid-cols-2'
  if (!grouped) {
    return <div className={grid}>{groups[0]?.lessons.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}</div>
  }
  return (
    <div className="flex flex-col gap-5">
      {groups.map((group, index) => {
        const id = groupId(prefs, group)
        const expanded = !prefs.collapsed.includes(id)
        const panel = `${base}-${index}`
        return (
          <section key={id} aria-label={group.label} data-testid="lesson-group" data-group={group.key}>
            <h2 className="mb-2 border-b pb-1">
              <GroupToggle group={group} expanded={expanded} onToggle={() => onToggleGroup(id)} controls={panel} />
            </h2>
            <div id={panel} hidden={!expanded} className={grid}>
              {expanded && group.lessons.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} headingLevel={3} />)}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function LessonRow({ lesson }: { lesson: Lesson }) {
  return (
    <tr className="group border-t transition-colors hover:bg-muted/50 focus-within:bg-muted/50" data-testid="lesson-row" data-lesson-id={lesson.id}>
      <td className="max-w-[28rem] px-3 py-2.5">
        <Link to={`/lezioni/${lesson.id}`} className="font-semibold leading-snug hover:underline">
          {lessonTitle(lesson)}
        </Link>
        {lesson.error && <p className="mt-0.5 text-xs text-danger">{lesson.error}</p>}
      </td>
      <td className="px-3 py-2.5 text-muted-foreground">{lesson.materia || '—'}</td>
      <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{lesson.data || '—'}</td>
      <td className="whitespace-nowrap px-3 py-2.5">{stateLabel(lesson) ?? '—'}</td>
      <td className="px-3 py-2.5"><PhaseDots phases={lesson.phases} /></td>
      <td className="px-3 py-2.5 text-right tabular-nums"><IssuesLink lesson={lesson} short /></td>
      <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">{formatCost(lesson.cost_usd)}</td>
      <td className="w-0 px-1 py-1"><LessonQuickActions lesson={lesson} layout="row" /></td>
    </tr>
  )
}

const COLUMNS = 8

function TableView({ groups, grouped, prefs, onSort, onToggleGroup }: ListProps) {
  const base = useId()
  const header = (label: string, key: LessonSortKey, className?: string) => (
    <SortHeader label={label} sortKey={key} prefs={prefs} onSort={onSort} className={className} />
  )
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full min-w-[52rem] border-collapse text-sm" data-testid="lesson-table">
        <caption className="sr-only">Lezioni, ordinate per {SORT_LABELS[prefs.sort].toLowerCase()}</caption>
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            {header('Titolo', 'titolo')}
            {header('Materia', 'materia')}
            {header('Data', 'data')}
            {header('Stato', 'stato')}
            <th scope="col" className="px-3 py-2 font-medium">Fasi</th>
            {header('Issue', 'issue', 'text-right')}
            {header('Costo', 'costo', 'text-right')}
            <th scope="col"><span className="sr-only">Azioni</span></th>
          </tr>
        </thead>
        {groups.map((group, index) => {
          const id = groupId(prefs, group)
          const expanded = !grouped || !prefs.collapsed.includes(id)
          const rows = `${base}-${index}`
          return (
            <tbody key={id} id={rows} data-testid={grouped ? 'lesson-group' : undefined} data-group={grouped ? group.key : undefined}>
              {grouped && (
                <tr className="border-t bg-muted/40">
                  <th scope="rowgroup" colSpan={COLUMNS} className="px-2 py-1 text-left">
                    <GroupToggle group={group} expanded={expanded} onToggle={() => onToggleGroup(id)} controls={rows} />
                  </th>
                </tr>
              )}
              {expanded && group.lessons.map((lesson) => <LessonRow key={lesson.id} lesson={lesson} />)}
            </tbody>
          )
        })}
      </table>
    </Card>
  )
}

export function LessonList(props: ListProps) {
  return props.prefs.view === 'tabella' ? <TableView {...props} /> : <CardsView {...props} />
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

/** Riga sopra l'elenco: quante lezioni, azzera filtri, raggruppa, ordina e vista. */
export function LessonViewControls({ shown, total, filtered, onReset, prefs, onChange }: {
  shown: number
  total: number
  filtered: boolean
  onReset: () => void
  prefs: LessonViewPrefs
  onChange: (patch: Partial<LessonViewPrefs>) => void
}) {
  const id = useId()
  const DirIcon = prefs.dir === 'asc' ? ArrowUp : ArrowDown
  const dirText = prefs.sort === 'data'
    ? prefs.dir === 'desc' ? 'dalla più recente' : 'dalla meno recente'
    : prefs.dir === 'asc' ? 'crescente' : 'decrescente'
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <p className="text-sm text-muted-foreground" role="status" data-testid="lesson-count">
        {filtered ? (
          <>
            <strong className="font-semibold text-foreground tabular-nums">{shown}</strong> di {total} lezioni
            <Button variant="link" size="sm" className="ml-1 h-auto px-1" onClick={onReset}>Azzera filtri</Button>
          </>
        ) : (
          <><strong className="font-semibold text-foreground tabular-nums">{total}</strong> {total === 1 ? 'lezione' : 'lezioni'}</>
        )}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-group`} className="text-xs">Raggruppa per</Label>
          <Select id={`${id}-group`} className="w-32" value={prefs.group} onChange={(e) => onChange({ group: e.target.value as LessonGroupBy })}>
            {(Object.keys(GROUP_LABELS) as LessonGroupBy[]).map((g) => <option key={g} value={g}>{GROUP_LABELS[g]}</option>)}
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-sort`} className="text-xs">Ordina per</Label>
          <div className="flex">
            <Select id={`${id}-sort`} className="w-40 rounded-r-none" value={prefs.sort}
              onChange={(e) => { const sort = e.target.value as LessonSortKey; onChange({ sort, dir: DEFAULT_DIR[sort] }) }}>
              {(Object.keys(SORT_LABELS) as LessonSortKey[]).map((s) => <option key={s} value={s}>{SORT_LABELS[s]}</option>)}
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
