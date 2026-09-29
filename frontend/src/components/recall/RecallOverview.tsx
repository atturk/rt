import { ArrowDown, ArrowUp, Brain, LayoutGrid, Send, Table2 } from 'lucide-react'
import { useId } from 'react'
import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { useSubjectsRecall, type LessonRecallStats, type SubjectRecall } from '@/api/recall'
import { LessonFilters } from '@/components/LessonFilters'
import { GroupToggle, Segmented, SortHeader } from '@/components/LessonList'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { lessonTitle, type Lesson } from '@/lib/format'
import { useFilteredLessons } from '@/lib/lessonFilters'
import type { LessonGroup, SortDir } from '@/lib/lessonView'
import { RECALL_TYPES, countStatus } from '@/lib/recall'
import {
  RECALL_DEFAULT_DIR,
  RECALL_SORT_LABELS,
  groupForRecall,
  pendingOf,
  subjectPath,
  subjectTotals,
  useRecallViewPrefs,
  type RecallSortKey,
  type RecallViewPrefs,
} from '@/lib/recallView'
import { cn } from '@/lib/utils'

const NOT_READY = 'serve prima la rielaborazione'

const subjectLink =
  'inline-flex h-8 items-center gap-2 rounded-md border border-input bg-card px-3 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring [&_svg]:size-4'

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`
}

/** "12 da porre · 3 risposte", o cosa manca per iniziare. */
function reserveText(stats?: LessonRecallStats) {
  if (!stats?.ready) return NOT_READY
  const total = Object.values(stats.questions).reduce((sum, byStatus) => sum + Object.values(byStatus).reduce((a, b) => a + b, 0), 0)
  if (total === 0) return 'nessuna domanda generata'
  return `${pendingOf(stats)} da porre · ${plural(stats.answers, 'risposta', 'risposte')}`
}

function LessonTitle({ lesson, stats, className }: { lesson: Lesson; stats?: LessonRecallStats; className?: string }) {
  return stats?.ready ? (
    <Link to={`/lezioni/${lesson.id}/recall`} className={cn('font-semibold leading-snug hover:underline', className)}>
      {lessonTitle(lesson)}
    </Link>
  ) : (
    <span className={cn('font-semibold leading-snug text-muted-foreground', className)}>{lessonTitle(lesson)}</span>
  )
}

function TelegramBadge({ stats }: { stats?: LessonRecallStats }) {
  if (!stats?.telegram) return null
  return (
    <Badge tone="warning" title="Sessione in corso su Telegram">
      <Send className="size-3" aria-hidden /> Telegram
    </Badge>
  )
}

function LessonRecallCard({ lesson, stats }: { lesson: Lesson; stats?: LessonRecallStats }) {
  return (
    <Card className="flex flex-col gap-1 p-4" data-testid="picker-lesson" data-lesson-id={lesson.id}>
      <LessonTitle lesson={lesson} stats={stats} />
      <span className="text-xs text-muted-foreground">{[lesson.data, reserveText(stats)].filter(Boolean).join(' · ')}</span>
      {stats?.telegram && (
        <div className="mt-1">
          <TelegramBadge stats={stats} />
        </div>
      )}
    </Card>
  )
}

/** Intestazione di una materia: apri/chiudi, totali e la sessione su tutte le sue lezioni. */
function SubjectHeader({ group, stats, subject, expanded, onToggle, controls }: {
  group: LessonGroup
  stats: Map<number, LessonRecallStats>
  subject?: SubjectRecall
  expanded: boolean
  onToggle: () => void
  controls: string
}) {
  const totals = subjectTotals(group.lessons, stats)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <GroupToggle group={group} expanded={expanded} onToggle={onToggle} controls={controls} />
      <span className="text-xs text-muted-foreground" data-testid="subject-pending">
        {plural(totals.pending, 'domanda da porre', 'domande da porre')}
      </span>
      {subject?.session && <Badge tone="success">Sessione in corso</Badge>}
      {group.key && (
        <span className="ml-auto">
          {totals.ready > 0 ? (
            <Link to={subjectPath(group.key)} className={subjectLink} data-testid="subject-recall">
              <Brain aria-hidden /> Recall della materia<span className="sr-only">: {group.label}</span>
            </Link>
          ) : (
            <span className="text-xs text-muted-foreground">Nessuna lezione pronta</span>
          )}
        </span>
      )}
    </div>
  )
}

type ViewProps = {
  groups: LessonGroup[]
  stats: Map<number, LessonRecallStats>
  subjects: Map<string, SubjectRecall>
  prefs: RecallViewPrefs
  onSort: (key: RecallSortKey) => void
  onToggleGroup: (id: string) => void
}

const groupId = (group: LessonGroup) => `materia:${group.key}`

function CardsView({ groups, stats, subjects, prefs, onToggleGroup }: ViewProps) {
  const base = useId()
  return (
    <div className="flex flex-col gap-5">
      {groups.map((group, index) => {
        const id = groupId(group)
        const expanded = !prefs.collapsed.includes(id)
        const panel = `${base}-${index}`
        return (
          <section key={id} aria-label={group.label} data-testid="recall-subject" data-subject={group.key}>
            <h2 className="mb-2 border-b pb-1">
              <SubjectHeader group={group} stats={stats} subject={subjects.get(group.key)} expanded={expanded} onToggle={() => onToggleGroup(id)} controls={panel} />
            </h2>
            <ul id={panel} hidden={!expanded} className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {expanded &&
                group.lessons.map((lesson) => (
                  <li key={lesson.id}>
                    <LessonRecallCard lesson={lesson} stats={stats.get(lesson.id)} />
                  </li>
                ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

const COLUMNS = 3 + RECALL_TYPES.length

function TableView({ groups, stats, subjects, prefs, onSort, onToggleGroup }: ViewProps) {
  const base = useId()
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full min-w-[40rem] border-collapse text-sm" data-testid="recall-table">
        <caption className="sr-only">Lezioni per materia, ordinate per {RECALL_SORT_LABELS[prefs.sort].toLowerCase()}</caption>
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <SortHeader label="Lezione" sortKey="titolo" prefs={prefs} onSort={onSort} />
            <SortHeader label="Data" sortKey="data" prefs={prefs} onSort={onSort} />
            {RECALL_TYPES.map((t) => (
              <th key={t.value} scope="col" className="px-3 py-2 text-right font-medium">
                {t.label} <span className="sr-only">da porre</span>
              </th>
            ))}
            <th scope="col" className="px-3 py-2 text-right font-medium">Risposte</th>
          </tr>
        </thead>
        {groups.map((group, index) => {
          const id = groupId(group)
          const expanded = !prefs.collapsed.includes(id)
          const rows = `${base}-${index}`
          return (
            <tbody key={id} id={rows} data-testid="recall-subject" data-subject={group.key}>
              <tr className="border-t bg-muted/40">
                <th scope="rowgroup" colSpan={COLUMNS} className="px-2 py-1 text-left font-normal">
                  <SubjectHeader group={group} stats={stats} subject={subjects.get(group.key)} expanded={expanded} onToggle={() => onToggleGroup(id)} controls={rows} />
                </th>
              </tr>
              {expanded &&
                group.lessons.map((lesson) => {
                  const s = stats.get(lesson.id)
                  return (
                    <tr key={lesson.id} className="border-t transition-colors hover:bg-muted/50" data-testid="picker-lesson" data-lesson-id={lesson.id}>
                      <td className="max-w-[28rem] px-3 py-2.5">
                        <LessonTitle lesson={lesson} stats={s} />
                        {!s?.ready && <span className="block text-xs text-muted-foreground">{NOT_READY}</span>}
                        {s?.telegram && <div className="mt-1"><TelegramBadge stats={s} /></div>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{lesson.data || '—'}</td>
                      {RECALL_TYPES.map((t) => (
                        <td key={t.value} className="px-3 py-2.5 text-right tabular-nums">
                          {s?.ready ? countStatus(s.questions, 'pending', t.value) : '—'}
                        </td>
                      ))}
                      <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">{s?.ready ? s.answers : '—'}</td>
                    </tr>
                  )
                })}
            </tbody>
          )
        })}
      </table>
    </Card>
  )
}

function ViewControls({ shown, total, filtered, onReset, prefs, onChange }: {
  shown: number
  total: number
  filtered: boolean
  onReset: () => void
  prefs: RecallViewPrefs
  onChange: (patch: Partial<RecallViewPrefs>) => void
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
          <Label htmlFor={`${id}-sort`} className="text-xs">Ordina per</Label>
          <div className="flex">
            <Select id={`${id}-sort`} className="w-44 rounded-r-none" value={prefs.sort}
              onChange={(e) => { const sort = e.target.value as RecallSortKey; onChange({ sort, dir: RECALL_DEFAULT_DIR[sort] }) }}>
              {(Object.keys(RECALL_SORT_LABELS) as RecallSortKey[]).map((s) => <option key={s} value={s}>{RECALL_SORT_LABELS[s]}</option>)}
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

/** /recall: le lezioni per materia, con la riserva di domande di ognuna e il recall della materia. */
export function RecallOverviewPage() {
  const lessons = useLessons()
  const recall = useSubjectsRecall()
  const { filters, setFilter, resetFilters, filtered } = useFilteredLessons(lessons.data)
  const { prefs, update, sortBy, toggleGroup } = useRecallViewPrefs()
  const stats = new Map((recall.data ?? []).flatMap((s) => s.lessons.map((l) => [l.lesson_id, l] as const)))
  const subjects = new Map((recall.data ?? []).map((s) => [s.materia, s]))
  const groups = groupForRecall(filtered, stats, prefs)
  const all = lessons.data ?? []
  const props: ViewProps = { groups, stats, subjects, prefs, onSort: sortBy, onToggleGroup: toggleGroup }
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">Active recall</h1>
      <p className="text-sm text-muted-foreground">
        Ripassa una lezione, oppure tutta una materia: la sessione della materia pesca le domande da tutte le sue lezioni.
      </p>
      <LessonFilters lessons={all} filters={filters} onChange={setFilter} />
      {lessons.isError && <Alert tone="danger">{errorMessage(lessons.error)}</Alert>}
      {recall.isError && <Alert tone="danger">{errorMessage(recall.error)}</Alert>}
      {lessons.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {lessons.data && all.length > 0 && (
        <ViewControls shown={filtered.length} total={all.length} filtered={Boolean(filters.q || filters.materia || filters.state)}
          onReset={resetFilters} prefs={prefs} onChange={update} />
      )}
      {lessons.data && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {all.length === 0 ? 'Nessuna lezione: importane una da un audio.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      {filtered.length > 0 && (prefs.view === 'tabella' ? <TableView {...props} /> : <CardsView {...props} />)}
    </section>
  )
}
