import { Check, Pencil, Undo2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useDecideIssue, useDecisions, useIssues, useLesson, useLessonDocument, useLessonJobs, useUndoDecision } from '@/api/hooks'
import { AudioPlayer } from '@/components/lesson/AudioPlayer'
import { AudioProvider, useLessonAudio } from '@/components/lesson/audio'
import { DocumentView } from '@/components/lesson/DocumentView'
import { JobsPanel } from '@/components/lesson/JobsPanel'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { wordDiff } from '@/lib/diff'
import { lessonTitle } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Area } from './types'

type IssueItem = Schemas['IssueItem']
type Issue = {
  id: string
  type: string
  severity: string
  unit_id?: string | null
  claim: string
  source_quote?: string | null
  reason: string
  suggested_fix?: string | null
  diplomatic_question?: string | null
}

const TYPE_LABELS: Record<string, string> = {
  ERR_CONCETTUALE: 'Errore concettuale',
  IMPRECISIONE: 'Imprecisione',
  OMISSIONE: 'Omissione',
  CHIARIMENTO: 'Chiarimento',
}
const SEVERITY: Record<string, [string, 'danger' | 'warning' | 'neutral']> = {
  high: ['alta', 'danger'],
  medium: ['media', 'warning'],
  low: ['bassa', 'neutral'],
}
const issueOf = (item: IssueItem) => item.issue as unknown as Issue
const idAt = (list: IssueItem[], i: number) => (list[i] ? issueOf(list[i]).id : undefined)

const DECISIONS: Record<string, string> = { accepted: 'accettata', rejected: 'originale mantenuto', edited: 'modificata' }

function decisionError(error: unknown): string {
  if (error instanceof ApiError && error.code === 'lesson_busy')
    return 'Sulla lezione sta lavorando un job: aspetta che finisca (o annullalo) e riprova.'
  return errorMessage(error)
}

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <p className="rounded-md bg-muted px-3 py-2 text-xs leading-relaxed" data-testid="issue-diff">
      {wordDiff(before, after).map((part, i) =>
        part.type === 'same' ? (
          <span key={i}>{part.text}</span>
        ) : part.type === 'removed' ? (
          <del key={i} className="bg-danger-soft text-danger">
            {part.text}
          </del>
        ) : (
          <ins key={i} className="bg-success-soft text-success no-underline">
            {part.text}
          </ins>
        ),
      )}
    </p>
  )
}

function IssueDetail({
  item,
  onDecide,
  busy,
  editing,
  setEditing,
  hasAudio,
}: {
  item: IssueItem
  onDecide: (decision: 'accepted' | 'rejected' | 'edited', text?: string) => void
  busy: boolean
  editing: boolean
  setEditing: (v: boolean) => void
  hasAudio: boolean
}) {
  const issue = item.issue as unknown as Issue
  const { seek } = useLessonAudio()
  const [text, setText] = useState(issue.suggested_fix ?? issue.claim)
  const [sevLabel, sevTone] = SEVERITY[issue.severity] ?? [issue.severity, 'neutral']
  const ctx = item.context
  return (
    <Card className="flex flex-col gap-3 p-4" data-testid="issue-detail" data-issue-id={issue.id}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-bold">{TYPE_LABELS[issue.type] ?? issue.type}</h2>
        <Badge tone={sevTone}>gravità {sevLabel}</Badge>
        {item.decision && <Badge tone="success">{DECISIONS[item.decision.decision] ?? item.decision.decision}</Badge>}
        {ctx?.start_s != null && (
          <Button variant="outline" size="sm" className="ml-auto h-7" disabled={!hasAudio} onClick={() => seek(ctx.start_s!)}>
            Ascolta {ctx.timecode}
          </Button>
        )}
      </div>
      {ctx?.unit_info && <p className="text-[11px] text-muted-foreground">Unità {ctx.unit_info}</p>}
      {issue.suggested_fix ? <Diff before={issue.claim} after={issue.suggested_fix} /> : <blockquote className="text-xs">{issue.claim}</blockquote>}
      <p className="text-xs">{issue.reason}</p>
      {issue.source_quote && (
        <p className="border-l-2 pl-2 text-xs text-muted-foreground">
          <span className="font-semibold">Docente:</span> {issue.source_quote}
        </p>
      )}
      {issue.diplomatic_question && <p className="text-xs italic text-muted-foreground">{issue.diplomatic_question}</p>}

      {editing ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            onDecide('edited', text)
          }}
        >
          <label htmlFor="edit-text" className="text-xs font-semibold">
            Testo corretto
          </label>
          <textarea
            id="edit-text"
            autoFocus
            rows={5}
            className="rounded-md border border-input bg-card p-2 text-sm"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setEditing(false)
            }}
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy || !text.trim()}>
              Salva modifica
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Annulla
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => onDecide('accepted')} aria-keyshortcuts="A">
            <Check /> Accetta correzione <kbd className="opacity-60">A</kbd>
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => onDecide('rejected')} aria-keyshortcuts="R">
            <X /> Mantieni originale <kbd className="opacity-60">R</kbd>
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setEditing(true)} aria-keyshortcuts="E">
            <Pencil /> Modifica <kbd className="opacity-60">E</kbd>
          </Button>
        </div>
      )}
    </Card>
  )
}

export function ReviewPage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  const issues = useIssues(id)
  const decisions = useDecisions(id)
  const jobs = useLessonJobs(id)
  const decide = useDecideIssue(id)
  const undo = useUndoDecision(id)
  const [params, setParams] = useSearchParams()
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const items = issues.data?.items ?? []
  const pending = items.filter((i) => !i.decision)
  const decided = items.filter((i) => i.decision)
  const ordered = [...pending, ...decided]
  const selectedId = params.get('issue') ?? (pending[0] ? issueOf(pending[0]).id : undefined) ?? (items[0] ? issueOf(items[0]).id : undefined) ?? null
  const selected = items.find((i) => issueOf(i).id === selectedId) ?? null
  const selectedIssue = selected ? issueOf(selected) : undefined
  const claim = selectedIssue?.claim
  const unitOfClaim = selectedIssue?.unit_id ?? null


  const select = (issueId: string | null | undefined) => {
    if (!issueId) return
    setEditing(false)
    const next = new URLSearchParams(params)
    next.set('issue', issueId)
    setParams(next, { replace: true })
  }

  const known = new Set(items.map((i) => issueOf(i).id))
  const lastDecision = [...(decisions.data ?? [])]
    .filter((d) => known.has(d.issue_id))
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .pop()

  const onDecide = (decision: 'accepted' | 'rejected' | 'edited', text?: string) => {
    if (!selected) return
    const current = issueOf(selected).id
    const wasWaiting = (jobs.data ?? []).some((j) => j.state === 'waiting_for_decision')
    const remaining = pending.filter((i) => issueOf(i).id !== current)
    const after = pending.findIndex((i) => issueOf(i).id === current)
    const next = remaining[after >= 0 ? Math.min(after, remaining.length - 1) : 0]
    setNotice(null)
    decide.mutate(
      { issueId: current, decision, text: decision === 'edited' ? text : undefined },
      {
        onSuccess: () => {
          setEditing(false)
          if (next) select(issueOf(next).id)
          else
            setNotice(
              wasWaiting
                ? 'Hai deciso tutte le issue: la pipeline in attesa è ripartita.'
                : 'Hai deciso tutte le issue: ora puoi generare il documento finale dalla pagina della lezione.',
            )
        },
      },
    )
  }

  const onUndo = () => {
    if (!lastDecision) return
    setNotice(null)
    undo.mutate(lastDecision.issue_id, { onSuccess: () => select(lastDecision.issue_id) })
  }

  // Scorciatoie: A accetta, R mantieni, E modifica, U annulla, frecce per navigare.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey || editing) return
      if (target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable || target.getAttribute('role') === 'slider'))
        return
      const index = ordered.findIndex((i) => issueOf(i).id === selectedId)
      const key = e.key.toLowerCase()
      if (key === 'a' && selected && !selected.decision) onDecide('accepted')
      else if (key === 'r' && selected && !selected.decision) onDecide('rejected')
      else if (key === 'e' && selected && !selected.decision) setEditing(true)
      else if (key === 'u') onUndo()
      else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') select(idAt(ordered, Math.min(index + 1, ordered.length - 1)))
      else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') select(idAt(ordered, Math.max(index - 1, 0)))
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (lesson.isPending || issues.isPending) return <p className="text-sm text-muted-foreground">Carico la revisione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  if (issues.isError) return <Alert tone="danger">{errorMessage(issues.error)}</Alert>
  const l = lesson.data
  const busy = decide.isPending || undo.isPending

  return (
    <AudioProvider>
      <section className="flex flex-col gap-4">
        <Link to={`/lezioni/${id}`} className="text-xs text-muted-foreground hover:underline">
          ← Torna alla lezione
        </Link>
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="mr-auto text-xl font-bold tracking-tight">Revisione · {lessonTitle(l)}</h1>
          <span className="text-sm" data-testid="review-counter">
            {issues.data.pending} da decidere su {issues.data.total}
          </span>
          <Button variant="outline" size="sm" disabled={!lastDecision || busy} onClick={onUndo} aria-keyshortcuts="U">
            <Undo2 /> Annulla ultima <kbd className="opacity-60">U</kbd>
          </Button>
        </div>
        {notice && <Alert data-testid="review-notice">{notice}</Alert>}
        {decide.isError && <Alert tone="danger">{decisionError(decide.error)}</Alert>}
        {undo.isError && <Alert tone="danger">{decisionError(undo.error)}</Alert>}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="flex min-w-0 flex-col gap-4">
            {l.has_audio && <AudioPlayer lessonId={id} sections={document.data?.sections ?? []} />}
            <Card className="max-h-[75vh] overflow-y-auto px-6 py-5">
              {document.data && <DocumentView document={document.data} hasAudio={l.has_audio} lessonId={id} highlightText={claim} highlightUnit={unitOfClaim} />}
            </Card>
          </div>
          <aside className="flex flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
            {selected ? (
              <IssueDetail
                key={issueOf(selected).id}
                item={selected}
                onDecide={onDecide}
                busy={busy}
                editing={editing}
                setEditing={setEditing}
                hasAudio={l.has_audio}
              />
            ) : (
              <Card className="p-4 text-sm text-muted-foreground">Nessuna issue per questa lezione.</Card>
            )}
            <JobsPanel lessonId={id} />
            <Card className="max-h-[45vh] overflow-y-auto p-2">
              {[
                ['Da decidere', pending],
                ['Decise', decided],
              ].map(([title, group]) =>
                (group as IssueItem[]).length ? (
                  <div key={title as string} className="mb-2">
                    <h3 className="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{title as string}</h3>
                    <ul aria-label={title as string}>
                      {(group as IssueItem[]).map((item) => {
                        const issue = item.issue as unknown as Issue
                        return (
                          <li key={issue.id}>
                            <button
                              type="button"
                              onClick={() => select(issue.id)}
                              aria-current={issue.id === selectedId ? 'true' : undefined}
                              data-issue={issue.id}
                              className={cn(
                                'flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left text-xs hover:bg-muted',
                                issue.id === selectedId && 'bg-accent text-accent-foreground',
                              )}
                            >
                              <span className="font-semibold">
                                {item.decision ? '✓ ' : ''}
                                {TYPE_LABELS[issue.type] ?? issue.type} · {item.context?.timecode ?? issue.unit_id}
                              </span>
                              <span className="line-clamp-2 text-muted-foreground">{issue.claim}</span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                ) : null,
              )}
            </Card>
          </aside>
        </div>
      </section>
    </AudioProvider>
  )
}

export const reviewArea: Area = {
  routes: [{ path: 'lezioni/:lessonId/revisione', element: <ReviewPage /> }],
}
