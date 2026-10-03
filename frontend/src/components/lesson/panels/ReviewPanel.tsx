import { Check, Pencil, Play, ShieldCheck, Undo2, X } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { errorMessage, type Schemas } from '@/api/client'
import { useDecideIssue, useDecisions, useIssues, useRunJob, useUndoDecision } from '@/api/hooks'
import { useCancelJob, useJobs } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ISSUE_ORDERS, parseIssueOrder, sortIssues } from '@/lib/issueOrder'
import { phaseProgress } from '@/lib/progress'
import { isActive } from '@/lib/jobs'
import { useLessonAudio } from '../audio'
import { decisionLabels, issueLabels, issueOf, paragraphIssue, type IssueItem } from '../reviewIssues'

export function ReviewPanel({ lesson: l, beforeAction = async () => undefined }: { lesson: Schemas['LessonDetail']; beforeAction?: () => Promise<void> }) {
  const issues = useIssues(l.id)
  const decisions = useDecisions(l.id)
  const jobs = useJobs({ lesson_id: l.id, limit: 20 })
  const run = useRunJob(l.id)
  const cancel = useCancelJob()
  const decide = useDecideIssue(l.id)
  const undo = useUndoDecision(l.id)
  const [params, setParams] = useSearchParams()
  const [group, setGroup] = useState<'pending' | 'decided'>('pending')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const { seek } = useLessonAudio()
  const items = issues.data?.items ?? []
  const order = parseIssueOrder(params.get('ordine'))
  const ordered = sortIssues(items, order, (item) => ({ ...issueOf(item), startSeconds: item.context?.start_s }))
  const pending = ordered.filter((i) => !i.decision)
  const decided = ordered.filter((i) => i.decision)
  const selected = items.find((i) => issueOf(i).id === params.get('issue')) ?? pending[0]
  const last = [...(decisions.data ?? [])].filter((d) => items.some((i) => issueOf(i).id === d.issue_id)).sort((a, b) => a.timestamp.localeCompare(b.timestamp)).pop()
  const active = jobs.data?.find((j) => isActive(j.state))
  const verifying = active && (active.type === 'run_pipeline' || active.type === 'run_phase') && (active.progress?.phase === 'review' || (active.payload as { phase?: string })?.phase === 'review')
  const progress = verifying ? phaseProgress(active) : null
  const waiting = jobs.data?.some((j) => j.state === 'waiting_for_decision' && j.decision?.kind === 'science_issue')
  const done = l.phases.review === 'VALID' || items.length > 0
  const busy = saving || decide.isPending || undo.isPending || run.isPending || !!active
  const select = (id: string) => { setEditing(false); const next = new URLSearchParams(params); next.set('issue', id); setParams(next, { replace: true }) }
  const action = async (fn: () => Promise<unknown>) => {
    setSaving(true); setFailure(null)
    try { await beforeAction(); await fn() } catch (error) { setFailure(errorMessage(error)) } finally { setSaving(false) }
  }
  const onDecide = (decision: 'accepted' | 'rejected' | 'edited', text?: string) => {
    if (!selected) return
    void action(async () => {
      await decide.mutateAsync({ issueId: issueOf(selected).id, decision, text })
      setEditing(false)
      const next = pending.find((i) => issueOf(i).id !== issueOf(selected).id)
      const query = new URLSearchParams(params)
      if (next) query.set('issue', issueOf(next).id); else query.delete('issue')
      setParams(query, { replace: true })
    })
  }
  if (issues.isPending) return <p className="text-meta text-muted-foreground">Carico la verifica…</p>
  if (issues.isError) return <Alert tone="danger">{errorMessage(issues.error)}</Alert>
  return <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
    <p className="font-semibold" role="status">{verifying ? 'In corso' : done ? pending.length ? `${pending.length} da decidere su ${items.length}` : 'Tutte decise' : 'Mai verificata'}</p>
    {verifying && <>
      <p className="text-meta text-muted-foreground">{progress?.detail ? `${progress.detail} · ` : ''}{items.length} issue trovate finora</p>
      <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(active.id)}>Interrompi</Button>
    </>}
    {done && pending.length === 0 && <>
      <p className="text-meta">{decided.length} issue decise: {['accepted', 'rejected', 'edited'].map((d) => `${decided.filter((i) => i.decision?.decision === d).length} ${decisionLabels[d] === 'accettata' ? 'accettate' : d === 'rejected' ? 'mantenute' : 'modificate'}`).join(', ')}.</p>
      <Button disabled={busy} onClick={() => void action(() => run.mutateAsync({ type: 'run_pipeline', with_review: true }))}><Play />Riprendi la pipeline</Button>
      {waiting && <Badge tone="neutral">Pipeline in attesa</Badge>}
    </>}
    {last && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void action(async () => { await undo.mutateAsync(last.issue_id); select(last.issue_id) })}><Undo2 />Annulla l'ultima</Button>}
    {selected && <IssueCard key={issueOf(selected).id} item={selected} busy={busy} editing={editing} onEditing={setEditing} onDecide={onDecide} onSeek={l.has_audio ? seek : undefined} />}
    {done && <>
      <div className="flex gap-2">
        <Button size="sm" variant={group === 'pending' ? 'default' : 'outline'} aria-pressed={group === 'pending'} onClick={() => setGroup('pending')}>Da decidere {pending.length}</Button>
        <Button size="sm" variant={group === 'decided' ? 'default' : 'outline'} aria-pressed={group === 'decided'} onClick={() => setGroup('decided')}>Decise {decided.length}</Button>
      </div>
      <Select aria-label="Ordine delle issue" value={order} onChange={(e) => { const next = new URLSearchParams(params); next.set('ordine', e.target.value); setParams(next, { replace: true }) }}>{ISSUE_ORDERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
      <ul aria-label={group === 'pending' ? 'Da decidere' : 'Decise'} className="flex flex-col gap-1">
        {(group === 'pending' ? pending : decided).map((item) => { const issue = issueOf(item); return <li key={issue.id}>
          <Button variant="ghost" className="h-auto w-full flex-col items-start whitespace-normal py-2 text-left text-meta" aria-current={selected === item ? 'true' : undefined} onClick={() => select(issue.id)}>
            <span>{issueLabels[issue.type] ?? issue.type} · {item.context?.timecode ?? issue.unit_id}</span>
            <span className="line-clamp-2 text-muted-foreground">{issue.claim}</span>
          </Button>
        </li> })}
      </ul>
    </>}
    <Button variant="outline" size="sm" disabled={busy || l.phases.rewrite !== 'VALID'} onClick={() => void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', force: done }))}><ShieldCheck />{done ? 'Verifica di nuovo tutta la lezione' : 'Verifica tutta la lezione'}</Button>
    {(failure || cancel.isError) && <Alert tone="danger">{failure ?? errorMessage(cancel.error)}</Alert>}
  </div>
}

function IssueCard({ item, busy, editing, onEditing, onDecide, onSeek }: {
  item: IssueItem; busy: boolean; editing: boolean; onEditing: (value: boolean) => void
  onDecide: (decision: 'accepted' | 'rejected' | 'edited', text?: string) => void; onSeek?: (seconds: number) => void
}) {
  const issue = issueOf(item)
  const paragraph = paragraphIssue(issue)
  const [text, setText] = useState(paragraph ? item.context?.unit_content ?? issue.claim : issue.suggested_fix ?? issue.claim)
  return <Card className="flex flex-col gap-3 p-3" data-testid="issue-detail">
    <div className="flex flex-wrap items-center gap-2"><b>{issueLabels[issue.type] ?? issue.type}</b><Badge tone={issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'neutral'}>{({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issue.severity] ?? issue.severity}</Badge></div>
    <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground"><span>Unità {issue.unit_id}</span>{onSeek && item.context?.start_s != null && <Button size="sm" variant="link" onClick={() => onSeek(item.context!.start_s!)}>Ascolta da {item.context.timecode}</Button>}</div>
    {!paragraph && <div><h3 className="mb-1 text-meta font-semibold">Correzione proposta</h3><p className="rounded-lg bg-muted p-3">{issue.suggested_fix ?? issue.claim}</p></div>}
    <p className="text-meta">{issue.reason}</p>
    {issue.source_quote && <p className="border-l-2 pl-2 text-meta text-muted-foreground">Docente: {issue.source_quote}</p>}
    {item.decision ? <Badge tone="success">{decisionLabels[item.decision.decision]}</Badge> : editing ? <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); onDecide('edited', text) }}>
      <label htmlFor="review-edit" className="text-meta">{paragraph ? 'Testo del paragrafo' : 'Testo corretto'}</label>
      <Textarea id="review-edit" autoFocus rows={5} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex gap-2"><Button type="submit" size="sm" disabled={busy || !text.trim()}>Salva modifica</Button><Button size="sm" variant="ghost" onClick={() => onEditing(false)}>Annulla</Button></div>
    </form> : <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy} onClick={() => onDecide('accepted')}><Check />Accetta</Button>
      {!paragraph && <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide('rejected')}><X />Mantieni</Button>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => onEditing(true)}><Pencil />Modifica</Button>
    </div>}
  </Card>
}
