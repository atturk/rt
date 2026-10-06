import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, Brain, Calendar, CalendarRange, FileText, ListFilter, Search, SquareCheck, SquareMinus, Tag, Trash2, User, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'

import { api, errorMessage, unwrap } from '@/api/client'
import { lessonExportUrl, useExportLessons } from '@/api/exports'
import { useSettings } from '@/api/settings'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

import { IconButton, IconLink } from '@/components/ui/icon-button'
import { MenuButton, type MenuSection } from '@/components/ui/menu'
import { Modal } from '@/components/ui/modal'
import { lessonTitle, type Lesson } from '@/lib/format'
import {
  GROUPING_LABELS, GROUP_CYCLE, groupBackground, PHONE_GROUP_LABELS, PHONE_SORT_LABELS, SORT_CYCLE, SORT_OPTIONS,
  markdownExportNote, STATUS_LABELS, groupLabel, lessonStatus, lessonSubtitle,
  type LessonStatus, type LessonsGrouping, type LessonsPrefs, type LessonsSort,
} from '@/lib/lessonsPage'
import type { LessonGroup } from '@/lib/lessonView'
import { useIsPhone } from '@/lib/phone'
import { selectionRecallPath } from '@/lib/recallView'
import { cn } from '@/lib/utils'

const GROUP_ICONS = { data: Calendar, mese: CalendarRange, materia: Tag, docente: User } as const

// ---------------------------------------------------------------- intestazione

/** Azioni dell'intestazione: raggruppa (icone), ordina, cerca, seleziona; sul telefono Raggruppa e Ordina a un tocco. */
export function LessonsHeaderActions({ prefs, onPrefs, query, onQuery, selecting, onSelecting }: {
  prefs: LessonsPrefs
  onPrefs: (patch: Partial<LessonsPrefs>) => void
  query: string
  onQuery: (q: string) => void
  selecting: boolean
  onSelecting: (on: boolean) => void
}) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [savedDateChoice, setSavedDateChoice] = useState<'data' | 'mese'>(() => (prefs.group === 'mese' ? 'mese' : 'data'))
  const dateChoice = prefs.group === 'data' || prefs.group === 'mese' ? prefs.group : savedDateChoice
  const DateIcon = dateChoice === 'mese' ? CalendarRange : Calendar
  const dateLabel = dateChoice === 'mese' ? 'Per mese' : 'Per data'
  const isDateActive = prefs.group === 'data' || prefs.group === 'mese'

  const handleDateClick = () => {
    if (prefs.group === 'data') {
      setSavedDateChoice('mese')
      onPrefs({ group: 'mese' })
    } else if (prefs.group === 'mese') {
      setSavedDateChoice('data')
      onPrefs({ group: 'data' })
    } else {
      onPrefs({ group: savedDateChoice })
    }
  }

  const selectGroup = (group: LessonsGrouping) => {
    if (prefs.group === 'data' || prefs.group === 'mese') {
      setSavedDateChoice(prefs.group)
    }
    onPrefs({ group })
  }

  const phone = useIsPhone()
  const input = useRef<HTMLInputElement>(null)
  const sortSection: MenuSection = {
    label: 'Ordina',
    items: (Object.keys(SORT_OPTIONS) as LessonsSort[]).map((sort) => ({ label: SORT_OPTIONS[sort], checked: prefs.sort === sort, onSelect: () => onPrefs({ sort }) })),
  }

  const cycleGroup = () => {
    if (prefs.group === 'data' || prefs.group === 'mese') {
      setSavedDateChoice(prefs.group)
    }
    const nextIndex = (GROUP_CYCLE.indexOf(prefs.group) + 1) % GROUP_CYCLE.length
    onPrefs({ group: GROUP_CYCLE[nextIndex] })
  }

  const cycleSort = () => {
    const nextIndex = (SORT_CYCLE.indexOf(prefs.sort) + 1) % SORT_CYCLE.length
    onPrefs({ sort: SORT_CYCLE[nextIndex] })
  }

  const GroupIcon = GROUP_ICONS[prefs.group]

  return (
    <>
      {!phone ? (
        <>
          <div role="group" aria-label="Raggruppa" className="flex rounded-md bg-muted p-0.5 max-md:hidden">
            <IconButton
              label={dateLabel}
              icon={DateIcon}
              aria-pressed={isDateActive}
              className={cn('hover:bg-card', isDateActive && 'bg-card shadow-[0_1px_3px_color-mix(in_oklch,var(--fg)_10%,transparent)]')}
              onClick={handleDateClick}
            />
            <IconButton
              label={GROUPING_LABELS.materia}
              icon={GROUP_ICONS.materia}
              aria-pressed={prefs.group === 'materia'}
              className={cn('hover:bg-card', prefs.group === 'materia' && 'bg-card shadow-[0_1px_3px_color-mix(in_oklch,var(--fg)_10%,transparent)]')}
              onClick={() => selectGroup('materia')}
            />
            <IconButton
              label={GROUPING_LABELS.docente}
              icon={GROUP_ICONS.docente}
              aria-pressed={prefs.group === 'docente'}
              className={cn('hover:bg-card', prefs.group === 'docente' && 'bg-card shadow-[0_1px_3px_color-mix(in_oklch,var(--fg)_10%,transparent)]')}
              onClick={() => selectGroup('docente')}
            />
          </div>
          <MenuButton label="Ordina" icon={ListFilter} sections={[sortSection]} className="max-md:hidden" />
        </>
      ) : (
        <>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-muted px-2.5 text-meta text-foreground md:hidden"
            aria-label={`Raggruppa: ${PHONE_GROUP_LABELS[prefs.group]} (tocca per cambiare)`}
            onClick={cycleGroup}
          >
            <GroupIcon className="size-3.5 shrink-0" aria-hidden />
            <span>{PHONE_GROUP_LABELS[prefs.group]}</span>
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-muted px-2.5 text-meta text-foreground md:hidden"
            aria-label={`Ordina: ${PHONE_SORT_LABELS[prefs.sort]} (tocca per cambiare)`}
            onClick={cycleSort}
          >
            <ListFilter className="size-3.5 shrink-0" aria-hidden />
            <span>{PHONE_SORT_LABELS[prefs.sort]}</span>
          </button>
          <IconButton
            label="Mostra la ricerca"
            icon={Search}
            className="md:hidden"
            aria-expanded={searchOpen || !!query}
            active={searchOpen || !!query}
            onClick={() => {
              setSearchOpen(!searchOpen)
              if (!searchOpen) setTimeout(() => input.current?.focus())
            }}
          />
        </>
      )}
      {/* Un solo campo "Cerca": il landmark non ha un nome suo, che lo ripeterebbe. */}
      <form
        role="search"
        onSubmit={(event) => event.preventDefault()}
        className={cn(
          'flex w-[220px] items-center gap-2 rounded-md border px-2.5 py-1.5 text-muted-foreground focus-within:border-foreground',
          'max-md:order-last max-md:w-full max-md:basis-full max-md:py-2.5',
          !searchOpen && !query && 'max-md:hidden',
        )}
      >
        <Search className="size-4 shrink-0" aria-hidden />
        <input
          ref={input}
          id="lessons-search"
          type="search"
          aria-label="Cerca"
          placeholder="Cerca"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          className="w-full min-w-0 bg-transparent text-meta text-foreground outline-none max-md:text-body"
        />
      </form>
      <IconButton
        label="Seleziona"
        icon={SquareCheck}
        aria-pressed={selecting}
        active={selecting}
        onClick={() => onSelecting(!selecting)}
      />
    </>
  )
}

// ---------------------------------------------------------------- righe

const DOT_CLASSES: Record<LessonStatus, string> = {
  'in-corso': 'bg-muted-foreground animate-[rt-pulse_1.8s_ease-in-out_infinite]',
  'da-verificare': 'bg-warning',
  errore: 'bg-danger',
  pronta: 'bg-muted-foreground',
  'da-completare': 'border border-muted-foreground bg-transparent',
}

function StatusDot({ status }: { status: LessonStatus }) {
  return (
    <span className="flex h-lh w-1.5 shrink-0 items-center justify-center text-body" title={STATUS_LABELS[status]} data-testid="lesson-status" data-status={status}>
      <span className={cn('block size-1.5 rounded-full', DOT_CLASSES[status])} aria-hidden />
      <span className="sr-only">{STATUS_LABELS[status]}</span>
    </span>
  )
}

/** Casella del design (16 px, accento quando spuntata) con l'area da toccare più grande. */
function Check({ label, checked, indeterminate = false, className, onChange }: { label: string; checked: boolean; indeterminate?: boolean; className?: string; onChange: (checked: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
      className={cn(
        'relative size-4 shrink-0 cursor-pointer appearance-none rounded-[4px] border border-muted-foreground bg-background',
        'before:absolute before:-inset-2.5 before:content-[""] max-md:before:-inset-3.5',
        'checked:border-accent-foreground checked:bg-accent indeterminate:border-accent-foreground indeterminate:bg-accent',
        'after:absolute checked:after:left-[4px] checked:after:top-[1px] checked:after:h-[9px] checked:after:w-[5px] checked:after:rotate-45 checked:after:border-accent-foreground checked:after:border-b-2 checked:after:border-r-2 checked:after:content-[""]',
        'indeterminate:after:inset-x-[3px] indeterminate:after:top-[6px] indeterminate:after:h-0.5 indeterminate:after:bg-accent-foreground indeterminate:after:content-[""]',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        className,
      )}
    />
  )
}

function LessonRow({ lesson, grouping, running, selecting, selected, onSelect }: {
  lesson: Lesson
  grouping: LessonsGrouping
  running: boolean
  selecting: boolean
  selected: boolean
  onSelect: (checked: boolean) => void
}) {
  const title = lessonTitle(lesson)
  const subtitle = lessonSubtitle(lesson, grouping)
  const titleId = useId()
  const row = 'flex items-start gap-3 rounded-lg px-2.5 py-3 text-foreground no-underline transition-colors hover:bg-muted max-md:px-2 max-md:py-2.5'
  const text = (
    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
      <span id={titleId} className="block text-body">{title}</span>
      {subtitle && (
        <span className="block text-meta text-muted-foreground" data-testid="lesson-subtitle">
          {subtitle}
        </span>
      )}
    </span>
  )
  // In selezione la riga è un'etichetta della casella (niente controlli dentro un link).
  return (
    <li data-testid="lesson-row" data-lesson-id={lesson.id}>
      {selecting ? (
        <label className={cn(row, 'cursor-pointer')}>
          <Check className="mt-0.5" label={`Seleziona ${title}`} checked={selected} onChange={onSelect} />
          {text}
        </label>
      ) : (
        <Link to={`/lezioni/${lesson.id}`} className={row} aria-labelledby={titleId}>
          <StatusDot status={lessonStatus(lesson, running)} />
          {text}
          <StudyRing lesson={lesson} />
        </Link>
      )}
    </li>
  )
}

/** Anello sommato sulle unità della scaletta attuale, allineato sul margine delle righe. */
function StudyRing({ lesson }: { lesson: Lesson }) {
  const learned = lesson.study_learned ?? 0
  const learning = lesson.study_learning ?? 0
  if (!learned && !learning) return null
  const total = lesson.unit_count ?? 0
  const learnedArc = total ? learned / total * 100 : 0
  const learningArc = total ? learning / total * 100 : 0
  return <span className="ml-2 flex shrink-0 self-center items-center gap-2 text-meta tabular-nums text-muted-foreground"
    role="img" aria-label={`${learned} unità apprese su ${total}, ${learning} in apprendimento`} data-testid="lesson-study-ring">
    <span aria-hidden>{learned}/{total}</span>
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden className="-rotate-90 fill-none stroke-[3]">
      <circle cx="11" cy="11" r="9" pathLength="100" className="stroke-muted" />
      <circle cx="11" cy="11" r="9" pathLength="100" className="stroke-success" strokeDasharray={`${learnedArc} ${100 - learnedArc}`} />
      <circle cx="11" cy="11" r="9" pathLength="100" className="stroke-warning" strokeDasharray={`${learningArc} ${100 - learningArc}`} strokeDashoffset={-learnedArc} />
    </svg>
  </span>
}

function GroupHeader({ group, grouping, selecting, selectedCount, onSelectGroup }: {
  group: LessonGroup
  grouping: LessonsGrouping
  selecting: boolean
  selectedCount: number
  onSelectGroup: (checked: boolean) => void
}) {
  const label = groupLabel(group, grouping)
  // Recall su un gruppo: si seleziona il gruppo (o le lezioni che si vogliono) e Recall nella barra in basso.
  return (
    <div className="flex items-center gap-3 px-2.5 pt-1 pb-0.5 max-md:gap-3 max-md:px-2">
      {selecting && (
        <Check
          label={`Seleziona il gruppo ${label}`}
          checked={selectedCount > 0 && selectedCount === group.lessons.length}
          indeterminate={selectedCount > 0 && selectedCount < group.lessons.length}
          onChange={onSelectGroup}
        />
      )}
      <h2 className="min-w-0 flex-1 text-meta font-semibold uppercase tracking-[.05em] text-muted-foreground">{label}</h2>
    </div>
  )
}

// ---------------------------------------------------------------- elenco e selezione

export function LessonsList({ groups, grouping, running, selecting, selected, onSelected }: {
  groups: LessonGroup[]
  grouping: LessonsGrouping
  running: Set<number>
  selecting: boolean
  selected: Set<number>
  onSelected: (next: Set<number>) => void
}) {
  const background = useSettings().data?.preferences?.sfondo_gruppi
  const toggle = (ids: number[], on: boolean) => {
    const next = new Set(selected)
    for (const id of ids) {
      if (on) next.add(id)
      else next.delete(id)
    }
    onSelected(next)
  }
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group, index) => (
        <section
          key={group.key || '-'}
          aria-label={groupLabel(group, grouping)}
          className={cn('rounded-xl px-1.5 pt-2.5 pb-1.5', background === 'niente' && 'px-0')}
          style={{ background: groupBackground(index, background) }}
          data-testid="lesson-group"
          data-group={group.key}
        >
          <GroupHeader
            group={group}
            grouping={grouping}
            selecting={selecting}
            selectedCount={group.lessons.filter((l) => selected.has(l.id)).length}
            onSelectGroup={(on) => toggle(group.lessons.map((l) => l.id), on)}
          />
          <ul className="flex flex-col">
            {group.lessons.map((lesson) => (
              <LessonRow
                key={lesson.id}
                lesson={lesson}
                grouping={grouping}
                running={running.has(lesson.id)}
                selecting={selecting}
                selected={selected.has(lesson.id)}
                onSelect={(on) => toggle([lesson.id], on)}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

/** Barra in basso con le azioni sulla selezione (schermata 01b): Recall, Scarica Markdown, Scarica zip, Elimina, Annulla. */
export function SelectionBar({ lessons, visibleLessons, onSelectAll, onCancel, onDeleted }: {
  lessons: Lesson[]
  visibleLessons: Lesson[]
  onSelectAll: (selected: boolean) => void
  onCancel: () => void
  onDeleted: (ids: number[]) => void
}) {
  const selectedIds = new Set(lessons.map((l) => l.id))
  const allSelected = visibleLessons.length > 0 && visibleLessons.every((l) => selectedIds.has(l.id))
  const finals = lessons.filter((l) => l.phases.build === 'VALID')
  const markdown = markdownExportNote(lessons)
  const ready = lessons.filter((l) => l.phases.rewrite === 'VALID')
  const [deleting, setDeleting] = useState(false)
  const start = useExportLessons()
  const [exportJob, setExportJob] = useState<{ id: string; state: string } | null>(null)
  const download = useRef<HTMLAnchorElement>(null)
  const downloaded = useRef<string | null>(null)
  const exporting = start.isPending || exportJob?.state === 'queued'
  const runExport = (format: 'markdown' | 'zip') => {
    start.mutate({ ids: (format === 'markdown' ? finals : lessons).map((l) => l.id), format, name: 'Lezioni selezionate' }, {
      onSuccess: (accepted) => setExportJob({ id: accepted.job_id, state: 'queued' }),
    })
  }
  useEffect(() => {
    if (exportJob?.state === 'succeeded' && download.current && downloaded.current !== exportJob.id) {
      downloaded.current = exportJob.id
      download.current.click()
    }
  }, [exportJob])
  return (
    <div
      role="region"
      aria-label="Selezione"
      data-testid="selection-bar"
      className="fixed bottom-[18px] left-1/2 z-10 flex max-w-[calc(100vw-32px)] -translate-x-1/2 flex-col gap-2 rounded-lg border bg-card py-2 pl-4 pr-3 shadow-panel md:left-[calc(50%+var(--rail-width)/2)] md:max-w-[calc(100vw-88px)] max-md:bottom-[calc(76px+env(safe-area-inset-bottom))]"
    >
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        <span className="mr-1 text-meta" aria-live="polite" data-testid="selection-count">
          {lessons.length === 1 ? '1 selezionata' : `${lessons.length} selezionate`}
        </span>
        <IconButton
          label={allSelected ? 'Deseleziona tutto' : 'Seleziona tutto'}
          icon={allSelected ? SquareMinus : SquareCheck}
          side="top"
          unavailable={visibleLessons.length === 0 ? 'nessuna lezione visibile' : null}
          onClick={() => onSelectAll(!allSelected)}
        />
        <IconLink
          label="Recall sulle lezioni selezionate"
          icon={Brain}
          side="top"
          to={ready.length ? selectionRecallPath(ready.map((l) => l.id)) : '/'}
          unavailable={lessons.length === 0 ? 'nessuna lezione selezionata' : ready.length === 0 ? 'nessuna lezione selezionata ha la rielaborazione' : null}
        />
        <IconButton
          label="Scarica Markdown"
          icon={FileText}
          side="top"
          onClick={() => runExport('markdown')}
          unavailable={exporting ? 'esportazione in corso' : markdown.unavailable}
          hint={markdown.hint}
        />
        <IconButton label="Scarica zip" icon={Archive} side="top" onClick={() => runExport('zip')} unavailable={exporting ? 'esportazione in corso' : lessons.length === 0 ? 'nessuna lezione selezionata' : null} />
        <IconButton
          label="Elimina le lezioni selezionate"
          icon={Trash2}
          side="top"
          aria-haspopup="dialog"
          unavailable={lessons.length === 0 ? 'nessuna lezione selezionata' : null}
          onClick={() => setDeleting(true)}
        />
        <IconButton label="Annulla" icon={X} side="top" onClick={onCancel} />
      </div>
      {start.isError && <Alert tone="danger">{errorMessage(start.error)}</Alert>}
      {exportJob && <JobProgress key={exportJob.id} jobId={exportJob.id} label="Esportazione delle lezioni" onFinished={(state) => setExportJob((current) => current ? { ...current, state } : null)} />}
      {exportJob?.state === 'succeeded' && (
        <a ref={download} className="text-meta text-link underline" href={lessonExportUrl(exportJob.id)} download>Scarica di nuovo</a>
      )}
      {deleting && <DeleteSelection lessons={lessons} onClose={() => setDeleting(false)} onDeleted={onDeleted} />}
    </div>
  )
}

type DeleteFailure = { lesson: Lesson; error: string }

/** Conferma e eliminazione delle lezioni selezionate, una per una (DELETE /lessons/{id}); gli errori restano per lezione. */
function DeleteSelection({ lessons, onClose, onDeleted }: { lessons: Lesson[]; onClose: () => void; onDeleted: (ids: number[]) => void }) {
  const [targets] = useState(lessons)
  const [typed, setTyped] = useState('')
  const [failures, setFailures] = useState<DeleteFailure[] | null>(null)
  const inputId = useId()
  const client = useQueryClient()
  const deletion = useMutation({
    mutationFn: async () => {
      const done: number[] = []
      const failed: DeleteFailure[] = []
      for (const lesson of targets) {
        try {
          await unwrap(api.DELETE('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: lesson.id } } }))
          done.push(lesson.id)
        } catch (error) {
          failed.push({ lesson, error: errorMessage(error) })
        }
      }
      return { done, failed }
    },
    onSuccess: ({ done, failed }) => {
      void client.invalidateQueries({ queryKey: ['lessons'] })
      onDeleted(done)
      if (failed.length) setFailures(failed)
      else onClose()
    },
  })
  const count = targets.length === 1 ? 'la lezione selezionata' : `le ${targets.length} lezioni selezionate`
  return (
    <Modal open onClose={onClose} title={failures ? 'Alcune lezioni non sono state eliminate' : `Eliminare ${count}?`} testId="delete-selection">
      {failures ? (
        <div className="mt-4 flex flex-col gap-3 text-meta">
          <ul className="flex flex-col gap-1.5" data-testid="delete-failures">
            {failures.map(({ lesson, error }) => (
              <li key={lesson.id}><span className="font-semibold">{lessonTitle(lesson)}</span>: <span className="text-danger">{error}</span></li>
            ))}
          </ul>
          <div className="flex justify-end"><Button size="sm" onClick={onClose}>Chiudi</Button></div>
        </div>
      ) : (
        <form
          className="mt-4 flex flex-col gap-2 text-meta"
          onSubmit={(event) => {
            event.preventDefault()
            if (typed === 'confermo') deletion.mutate()
          }}
        >
          <ul className="mb-1 flex max-h-40 flex-col gap-0.5 overflow-auto text-body">
            {targets.map((lesson) => <li key={lesson.id}>{lessonTitle(lesson)}</li>)}
          </ul>
          <label htmlFor={inputId}>Eliminare definitivamente {targets.length === 1 ? 'la lezione e tutti i suoi file' : 'queste lezioni e tutti i loro file'}? Scrivi confermo</label>
          <input id={inputId} className="min-h-10 rounded-md border bg-card p-2 text-body" value={typed} autoFocus onChange={(event) => setTyped(event.target.value)} />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>Annulla</Button>
            <Button type="submit" variant="destructive" size="sm" disabled={typed !== 'confermo' || deletion.isPending}>
              {deletion.isPending ? 'Elimino…' : 'Elimina'}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
