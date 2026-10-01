import { useId, type ReactNode } from 'react'
import { Link } from 'react-router'

import { GroupToggle, SortHeader, ViewToolbar } from '@/components/LessonList'
import { Card } from '@/components/ui/card'
import { lessonTitle, type Lesson } from '@/lib/format'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { GROUP_LABELS, groupLessons, sortLessons, type LessonGroup, type LessonGroupBy, type SortDir } from '@/lib/lessonView'
import { useViewPrefs, type ViewPrefsSpec } from '@/lib/viewPrefs'

/**
 * Elenco di lezioni con la stessa barra della dashboard (Cerca, Raggruppa per, Ordina per,
 * Schede/Tabella), per le pagine che scelgono una lezione su cui lavorare (Review, Immagini).
 * Ogni pagina dà la sua scheda e le colonne in più della tabella; "extra" è l'ordinamento
 * proprio della pagina (es. issue da valutare).
 */
export type BrowserSortKey = 'data' | 'titolo' | 'materia' | 'extra'

export type BrowserColumn = { label: string; className?: string; cell: (lesson: Lesson) => ReactNode }

const collator = new Intl.Collator('it', { sensitivity: 'base', numeric: true })

function sortFor(lessons: Lesson[], sort: BrowserSortKey, dir: SortDir, extra?: (lesson: Lesson) => number | string): Lesson[] {
  if (sort !== 'extra' || !extra) return sortLessons(lessons, sort === 'extra' ? 'data' : sort, dir)
  const sign = dir === 'asc' ? 1 : -1
  return [...sortLessons(lessons, 'data', 'desc')].sort((a, b) => {
    const [x, y] = [extra(a), extra(b)]
    return sign * (typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x), String(y)))
  })
}

export function LessonBrowser({ storageKey, lessons, total, card, columns, link, extraSort, testId, emptyText }: {
  storageKey: string
  /** Lezioni della pagina (già ristrette, es. quelle con issue). */
  lessons: Lesson[]
  /** Quante lezioni ha la pagina senza filtri. */
  total?: number
  card: (lesson: Lesson) => ReactNode
  columns: BrowserColumn[]
  /** Dove porta il titolo nella tabella (null: non è un link). */
  link: (lesson: Lesson) => string | null
  extraSort?: { label: string; dir: SortDir; value: (lesson: Lesson) => number | string }
  testId: string
  emptyText: string
}) {
  const { filters, setFilter, resetFilters, filtered } = useFilteredLessons(lessons)
  const spec: ViewPrefsSpec<BrowserSortKey, LessonGroupBy> = {
    sorts: extraSort ? ['data', 'titolo', 'materia', 'extra'] : ['data', 'titolo', 'materia'],
    groups: Object.keys(GROUP_LABELS) as LessonGroupBy[],
    defaults: { view: 'schede', sort: 'data', dir: 'desc', group: 'nessuno', collapsed: [] },
    defaultDir: { data: 'desc', titolo: 'asc', materia: 'asc', extra: extraSort?.dir ?? 'desc' },
  }
  const { prefs, update, sortBy, toggleGroup } = useViewPrefs(storageKey, spec)
  const sortLabels = { data: 'Data', titolo: 'Titolo', materia: 'Materia', ...(extraSort ? { extra: extraSort.label } : {}) } as Record<BrowserSortKey, string>
  const groups = groupLessons(sortFor(filtered, prefs.sort, prefs.dir, extraSort?.value), prefs.group, prefs.sort === 'data' ? prefs.dir : 'desc')
  const grouped = prefs.group !== 'nessuno'
  const searchId = useId()
  const base = useId()
  const hasFilters = Boolean(filters.q || filters.materia || filters.state)
  const count = total ?? lessons.length
  const groupId = (group: LessonGroup) => `${prefs.group}:${group.key}`
  return (
    <>
      {count > 0 && (
        <ViewToolbar<BrowserSortKey, LessonGroupBy> shown={filtered.length} total={count} filtered={hasFilters} onReset={resetFilters}
          search={{ id: searchId, value: filters.q, onChange: (value) => setFilter('q', value) }}
          prefs={prefs} onChange={update} sortLabels={sortLabels} groupLabels={GROUP_LABELS} defaultDir={spec.defaultDir} />
      )}
      {count > 0 && filtered.length === 0 && <Card className="p-6 text-sm text-muted-foreground">{emptyText}</Card>}
      {filtered.length > 0 && prefs.view === 'schede' && (
        <div className="flex flex-col gap-5">
          {groups.map((group, index) => {
            const id = groupId(group)
            const expanded = !grouped || !prefs.collapsed.includes(id)
            const panel = `${base}-${index}`
            return (
              <section key={id} aria-label={grouped ? group.label : undefined} data-testid={grouped ? 'lesson-group' : undefined} data-group={grouped ? group.key : undefined}>
                {grouped && (
                  <h2 className="mb-2 border-b pb-1">
                    <GroupToggle group={group} expanded={expanded} onToggle={() => toggleGroup(id)} controls={panel} />
                  </h2>
                )}
                <ul id={panel} hidden={!expanded} className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {expanded && group.lessons.map((lesson) => <li key={lesson.id}>{card(lesson)}</li>)}
                </ul>
              </section>
            )
          })}
        </div>
      )}
      {filtered.length > 0 && prefs.view === 'tabella' && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[40rem] border-collapse text-sm" data-testid={`${testId}-table`}>
            <caption className="sr-only">Lezioni, ordinate per {sortLabels[prefs.sort].toLowerCase()}</caption>
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <SortHeader label="Lezione" sortKey="titolo" prefs={prefs} onSort={sortBy} />
                <SortHeader label="Materia" sortKey="materia" prefs={prefs} onSort={sortBy} />
                <SortHeader label="Data" sortKey="data" prefs={prefs} onSort={sortBy} />
                {columns.map((c, i) =>
                  extraSort && i === 0 ? (
                    <SortHeader key={c.label} label={c.label} sortKey="extra" prefs={prefs} onSort={sortBy} className={c.className} />
                  ) : (
                    <th key={c.label} scope="col" className={`px-3 py-2 font-medium ${c.className ?? ''}`}>{c.label}</th>
                  ),
                )}
              </tr>
            </thead>
            {groups.map((group, index) => {
              const id = groupId(group)
              const expanded = !grouped || !prefs.collapsed.includes(id)
              const rows = `${base}-t${index}`
              return (
                <tbody key={id} id={rows} data-testid={grouped ? 'lesson-group' : undefined} data-group={grouped ? group.key : undefined}>
                  {grouped && (
                    <tr className="border-t bg-muted/40">
                      <th scope="rowgroup" colSpan={3 + columns.length} className="px-2 py-1 text-left font-normal">
                        <GroupToggle group={group} expanded={expanded} onToggle={() => toggleGroup(id)} controls={rows} />
                      </th>
                    </tr>
                  )}
                  {expanded &&
                    group.lessons.map((lesson) => {
                      const href = link(lesson)
                      return (
                        <tr key={lesson.id} className="border-t transition-colors hover:bg-muted/50" data-testid={testId} data-lesson-id={lesson.id}>
                          <td className="max-w-[28rem] px-3 py-2.5">
                            <TitleCell lesson={lesson} href={href} />
                          </td>
                          <td className="px-3 py-2.5 text-muted-foreground">{lesson.materia || '—'}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{lesson.data || '—'}</td>
                          {columns.map((c) => (
                            <td key={c.label} className={`px-3 py-2.5 ${c.className ?? ''}`}>{c.cell(lesson)}</td>
                          ))}
                        </tr>
                      )
                    })}
                </tbody>
              )
            })}
          </table>
        </Card>
      )}
    </>
  )
}

function TitleCell({ lesson, href }: { lesson: Lesson; href: string | null }) {
  return href ? (
    <LinkTitle href={href}>{lessonTitle(lesson)}</LinkTitle>
  ) : (
    <span className="font-semibold leading-snug text-muted-foreground">{lessonTitle(lesson)}</span>
  )
}

function LinkTitle({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link to={href} className="font-semibold leading-snug hover:underline">
      {children}
    </Link>
  )
}
