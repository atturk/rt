import { ReviewUnits } from './ReviewUnits'
import { usePreference } from '@/lib/preferences'
import { IconButton } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { Tooltip } from '@/components/ui/tooltip'
import { EditorState } from '@codemirror/state'
import { ArrowDownWideNarrow, Check, Eye, MoreHorizontal, RotateCcw, Pencil, ShieldCheck, Undo2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useDecideIssue, useIssues, useRunJob, useUndoDecision, useReviewUnits } from '@/api/hooks'
import { useCancelJob, useJobs } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { parseIssueOrder, sortIssues } from '@/lib/issueOrder'
import { useIsPhone } from '@/lib/phone'
import { issueRange } from '../lessonReview'
import { isActive } from '@/lib/jobs'
import { useLessonAudio } from '../audio'
import { decisionLabels, issueLabels, issueOf, paragraphIssue, type IssueItem } from '../reviewIssues'

export function ReviewPanel({ lesson: l, beforeAction = async () => undefined, markdown }: { markdown?: string; lesson: Schemas['LessonDetail']; beforeAction?: () => Promise<void> }) {
  const issues = useIssues(l.id)
  const reviewUnits = useReviewUnits(l.id)
  const jobs = useJobs({ lesson_id: l.id, limit: 20 })
  const run = useRunJob(l.id)
  const cancel = useCancelJob()
  const decide = useDecideIssue(l.id)
  const undo = useUndoDecision(l.id)
  const [params, setParams] = useSearchParams()
  const initialIssue = useRef(params.get('issue'))
  const [savedOrder, setSavedOrder] = usePreference('review.order', 'cronologico')
  const [showDecided, setShowDecided] = useState(false)
  const [confirmation, setConfirmation] = useState<'all' | string | null>(null)
  const [queuedUnits, setQueuedUnits] = useState<string[]>([])
  const [changedIssues, setChangedIssues] = useState<string[]>([])
  const [cardFailure, setCardFailure] = useState<{ id: string; message: string } | null>(null)
  const [message, setMessage] = useState<{ id: string; label: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const phone = useIsPhone()
  const { seek } = useLessonAudio()
  const items = issues.data?.items ?? []
  const messageItem = message ? items.find(item => issueOf(item).id === message.id) : undefined
  const order = parseIssueOrder(params.get('ordine') ?? savedOrder)
  const ordered = sortIssues(items, order, item => ({ ...issueOf(item), startSeconds: item.context?.start_s }))
  const pending = ordered.filter(item => !item.decision || item.needs_reconfirmation)
  // Anche le issue di unità sparite restano raggiungibili.
  const units = [...(reviewUnits.data ?? [])]
  for (const item of items) {
    const id = issueOf(item).unit_id ?? ''
    if (!units.some(unit => unit.unit_id === id)) units.push({ unit_id: id, title: 'Unità non ritrovata', state: 'changed', issues_total: 0, issues_pending: 0 })
  }
  const needsReview = (reviewUnits.data ?? []).filter(unit => ['never', 'changed', 'failed'].includes(unit.state))
  const included = (reviewUnits.data ?? []).filter(unit => unit.state !== 'excluded')
  const reviewedCount = included.filter(unit => ['ok', 'issues'].includes(unit.state)).length
  const focusedUnit = params.get('review_unit')
  const selected = ordered.find(item => issueOf(item).id === params.get('issue') && (!item.decision || item.needs_reconfirmation || showDecided)) ?? pending.find(item => !focusedUnit || issueOf(item).unit_id === focusedUnit) ?? (showDecided ? ordered.find(item => !focusedUnit || issueOf(item).unit_id === focusedUnit) : undefined)
  const hiddenInitialIssue = items.some(item => issueOf(item).id === params.get('issue') && item.decision && !item.needs_reconfirmation)
  const selectedId = selected ? issueOf(selected).id : null
  useEffect(() => {
    if (showDecided) initialIssue.current = null
    if (!selectedId || params.get('issue') === selectedId) return
    // Un link a una scelta nascosta resta disponibile fino a Mostra decise.
    if (params.get('issue') === initialIssue.current && hiddenInitialIssue) return
    const next = new URLSearchParams(params)
    next.set('issue', selectedId)
    setParams(next, { replace: true })
  }, [selectedId, params, setParams, hiddenInitialIssue, showDecided])
  const active = jobs.data?.find(job => job.type !== 'documents' && isActive(job.state))
  const verifying = !!active && (['review_unit', 'review_part'].includes(active.type) || active.type === 'run_phase' && (active.payload as { phase?: string })?.phase === 'review' || active.type === 'run_pipeline' && active.progress?.phase === 'review')
  const payload = active?.payload as { units?: string[]; unit?: string } | undefined
  const jobUnits = payload?.units ?? (payload?.unit ? [payload.unit] : included.map(unit => unit.unit_id))
  const pendingUnits = verifying ? Array.isArray(active?.progress?.pending_units) ? active.progress.pending_units as string[] : active?.progress?.completed ? [] : jobUnits : []
  const runningUnits = verifying && active?.state === 'running' ? Array.isArray(active.progress?.running_units) ? active.progress.running_units as string[] : pendingUnits : []
  const waitingUnits = [...new Set([...pendingUnits.filter(id => !runningUnits.includes(id)), ...queuedUnits])]
  const complete = !verifying && !reviewUnits.isPending && pending.length === 0 && needsReview.length === 0 && (l.phases.review === 'VALID' || reviewedCount > 0)
  const documentsUpdating = jobs.data?.some(job => job.type === 'documents' && isActive(job.state))
  const status = pending.length ? `${pending.length} da decidere` : complete ? 'Tutte decise' : reviewedCount > 0 ? `${needsReview.length} unità da verificare` : 'Mai verificata'
  const busy = saving || decide.isPending || undo.isPending || run.isPending || !!active
  const decisionBusy = (unit?: string | null) => saving || decide.isPending || undo.isPending || run.isPending || !!active && (!verifying || pendingUnits.includes(unit ?? ''))
  const select = (id: string) => { setEditing(false); const next = new URLSearchParams(params); next.set('issue', id); next.delete('review_unit'); setParams(next, { replace: true }) }
  const action = async (fn: () => Promise<unknown>) => {
    setSaving(true); setFailure(null)
    try { await beforeAction(); await fn() } catch (error) { setFailure(errorMessage(error)) } finally { setSaving(false) }
  }
  const onDecide = (decision: 'accepted' | 'rejected' | 'edited', text?: string) => {
    if (!selected) return
    void action(async () => {
      try {
        await decide.mutateAsync({ issueId: issueOf(selected).id, decision, text })
        setCardFailure(null)
        setMessage({ id: issueOf(selected).id, label: `Correzione ${decisionLabels[decision]}.` })
      } catch (error) {
        const id = issueOf(selected).id
        setCardFailure({ id, message: errorMessage(error) })
        if (error instanceof ApiError && error.code === 'claim_changed') setChangedIssues(old => [...old, id])
        return
      }
      setEditing(false)
      const next = pending.find(item => issueOf(item).id !== issueOf(selected).id)
      const query = new URLSearchParams(params)
      query.delete('review_unit')
      if (next) query.set('issue', issueOf(next).id); else query.delete('issue')
      setParams(query, { replace: true })
    })
  }
  const verify = (unit?: string, force = false) => {
    const list = unit ? [unit] : needsReview.map(u => u.unit_id)
    setQueuedUnits(list)
    void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', ...(unit ? { unit } : !force && list.length ? { units: list } : {}), ...(force ? { force: true } : {}) })).finally(() => setQueuedUnits([]))
  }
  const orderedUnits = [...units].sort((a, b) => {
    if (order !== 'gravita') return 0
    const rank = (unit: string) => Math.min(3, ...pending.filter(item => issueOf(item).unit_id === unit).map(item => { const value = ['high', 'medium', 'low'].indexOf(issueOf(item).severity); return value < 0 ? 3 : value }))
    return rank(a.unit_id) - rank(b.unit_id)
  })
  const verifyUnavailable = reviewUnits.isPending ? 'Carico le unità' : reviewUnits.isError ? 'Stato delle unità non disponibile' : busy ? 'Lavorazione in corso' : l.phases.rewrite !== 'VALID' ? 'Rielaborazione non pronta' : needsReview.length === 0 ? 'Tutte le unità sono verificate' : null
  if (issues.isPending) return <p className="text-meta text-muted-foreground">Carico la verifica…</p>
  if (issues.isError) return <Alert tone="danger">{errorMessage(issues.error)}</Alert>
  return <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="font-semibold" role="status">{verifying ? 'In corso · ' : ''}{status} · {reviewedCount}/{included.length} unità verificate</p>
      <div className="flex items-center gap-1">
        <IconButton label="Verifica" icon={ShieldCheck} variant="solid" unavailable={verifyUnavailable} hint={`${needsReview.length} unità da verificare`} badge={needsReview.length ? <span className="absolute -right-1 -top-1 rounded-full bg-foreground px-1 text-meta text-background">{needsReview.length}</span> : undefined} onClick={() => verify()} />
        <IconButton label="Ordine delle issue" icon={ArrowDownWideNarrow} hint={order === 'cronologico' ? 'Cronologico' : 'Gravità'} onClick={() => { const nextOrder = order === 'cronologico' ? 'gravita' : 'cronologico'; setSavedOrder(nextOrder); const next = new URLSearchParams(params); next.set('ordine', nextOrder); setParams(next, { replace: true }) }} />
        <IconButton label="Mostra decise" icon={Eye} active={showDecided} aria-pressed={showDecided} onClick={() => setShowDecided(!showDecided)} />
        <LinkMenuButton label="Azioni della verifica" icon={MoreHorizontal} unavailable={busy ? 'Lavorazione in corso' : undefined} items={[{ label: 'Riesegui tutta la lezione…', onSelect: () => setConfirmation('all') }]} />
      </div>
    </div>
    <p className="text-meta text-muted-foreground" data-testid="documents-status">{l.phases.build === 'VALID' && !documentsUpdating ? 'Documento aggiornato' : 'Documento in aggiornamento'}{units.some(u => u.state === 'excluded') ? ` · ${units.filter(u => u.state === 'excluded').length} escluse` : ''}</p>
    {verifying && <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(active!.id)}>Interrompi</Button>}
    {confirmation !== null && <Card className="flex flex-col gap-2 p-3" role="group" aria-label={confirmation === 'all' ? 'Riesegui tutta la lezione' : `Riesegui l’unità ${confirmation}`}>
      <p>{confirmation === 'all' ? 'Verifica tutte le unità, comprese quelle già verificate.' : `Verifica di nuovo l’unità ${confirmation}.`} Le decisioni restano registrate.</p>
      <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => { verify(confirmation === 'all' ? undefined : confirmation, true); setConfirmation(null) }}>Riesegui {confirmation === 'all' ? 'tutte le unità' : 'l’unità'}</Button><Button variant="ghost" size="sm" onClick={() => setConfirmation(null)}>Annulla</Button></div>
    </Card>}
    {reviewUnits.isError && <Alert tone="danger">{errorMessage(reviewUnits.error)}</Alert>}
    {complete && !showDecided ? <Card data-testid="review-summary" className="flex flex-col gap-2 p-4 text-meta"><Check className="size-6 text-success" /><p className="font-semibold">La verifica è tutta decisa.</p><p>{ordered.filter(item => item.decision?.decision === 'accepted').length} accettate · {ordered.filter(item => item.decision?.decision === 'edited').length} modificate · {ordered.filter(item => item.decision?.decision === 'rejected').length} mantenute</p></Card> : <ReviewUnits units={orderedUnits} busy={busy} running={runningUnits} queued={waitingUnits} missing={units.filter(unit => !(reviewUnits.data ?? []).some(row => row.unit_id === unit.unit_id)).map(unit => unit.unit_id)} selectedUnit={(selected ? issueOf(selected).unit_id : null) ?? params.get('review_unit')} items={ordered.filter(item => !item.decision || item.needs_reconfirmation || showDecided)} onVerify={unit => verify(unit)} onReverify={setConfirmation} onClassifier={() => { const next = new URLSearchParams(params); next.set('panel', 'classificatore'); next.delete('issue'); next.delete('review_unit'); setParams(next) }} renderIssues={unit => <ul aria-label={`Issue dell’unità ${unit}`} className="flex flex-col gap-1">
      {ordered.filter(item => issueOf(item).unit_id === unit && (!item.decision || item.needs_reconfirmation || showDecided)).map(item => <li key={issueOf(item).id}>{selected === item ? <IssueCard key={`${issueOf(item).id}:${item.decision?.timestamp}:${item.needs_reconfirmation}`} item={item} busy={decisionBusy(issueOf(item).unit_id)} editing={editing} onEditing={setEditing} onDecide={onDecide} onSeek={l.has_audio ? seek : undefined} phone={phone} failure={cardFailure?.id === issueOf(item).id ? cardFailure.message : undefined} changed={changedIssues.includes(issueOf(item).id) || markdown !== undefined && (!item.decision || item.needs_reconfirmation) && !issueRange(EditorState.create({ doc: markdown }), item)} onUndo={() => void action(async () => { await undo.mutateAsync(issueOf(item).id); setMessage(null); select(issueOf(item).id) })} /> : <Button variant="ghost" className="h-auto w-full flex-col items-start whitespace-normal py-2 text-left text-meta" aria-current={selected === item ? 'true' : undefined} onClick={() => select(issueOf(item).id)}><span>{issueLabels[issueOf(item).type]} · {item.context?.timecode}</span><span className="line-clamp-2 text-muted-foreground">{item.decision?.resolved_text ?? issueOf(item).suggested_fix ?? issueOf(item).claim}</span>{item.decision && <span>{item.needs_reconfirmation ? 'Da riconfermare' : decisionLabels[item.decision.decision]}</span>}</Button>}</li>)}
    </ul>} />}
    {message && <Card role="log" aria-live="polite" data-testid="review-decision-message" className="sticky bottom-0 flex items-center justify-between gap-2 bg-card p-3 text-meta"><span>{message.label}</span><Button variant="ghost" size="sm" disabled={decisionBusy(messageItem ? issueOf(messageItem).unit_id : null)} onClick={() => void action(async () => { await undo.mutateAsync(message.id); select(message.id); setMessage(null) })}><Undo2 />Annulla</Button></Card>}
    {(failure || cancel.isError) && <Alert tone="danger">{failure ?? errorMessage(cancel.error)}</Alert>}
  </div>
}

function IssueCard({ item, failure, busy, editing, onEditing, onDecide, onSeek, phone, changed, onUndo }: {
  failure?: string; phone: boolean; changed: boolean; onUndo: () => void
  item: IssueItem; busy: boolean; editing: boolean; onEditing: (value: boolean) => void
  onDecide: (decision: 'accepted' | 'rejected' | 'edited', text?: string) => void; onSeek?: (seconds: number) => void
}) {
  const issue = issueOf(item)
  const paragraph = paragraphIssue(issue)
  const suggestion = !paragraph && item.fix_text === null && !item.decision?.resolved_text
  const readOnly = !!item.decision && !item.needs_reconfirmation
  const proposed = item.decision?.resolved_text ?? (paragraph ? item.context?.unit_content ?? issue.claim : suggestion ? issue.claim : item.fix_text ?? issue.suggested_fix ?? issue.claim)
  const cannotApply = changed || !!issue.unanchored
  const [text, setText] = useState(proposed)
  const box = useRef<HTMLDivElement>(null)
  const controls = useRef<HTMLDivElement>(null)
  const prepareInput = useCallback((node: HTMLTextAreaElement | null) => {
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight}px`
    node.setSelectionRange(node.value.length, node.value.length)
  }, [])
  const modified = text !== proposed
  const cancelEdit = () => { setText(proposed); onEditing(false) }
  const apply = () => {
    if (!modified) { onEditing(false); return }
    if (!text.trim() || busy) return
    onEditing(false)
    onDecide('edited', text)
  }
  useEffect(() => {
    if (!editing || readOnly) return
    const outside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node) && !controls.current?.contains(event.target as Node)) apply()
    }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [editing, readOnly, modified, text, busy]) // oxlint-disable-line react-hooks/exhaustive-deps
  return <Card className="flex flex-col gap-3 p-3" data-testid="issue-detail">
    <div className="flex flex-wrap items-center gap-2"><b>{issueLabels[issue.type] ?? issue.type}</b><Badge tone={issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'neutral'}>{({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issue.severity] ?? issue.severity}</Badge></div>
    <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground"><span>Unità {issue.unit_id}</span>{!readOnly && onSeek && item.context?.start_s != null && <Button size="sm" variant="link" onClick={() => onSeek(item.context!.start_s!)}>Ascolta da {item.context.timecode}</Button>}</div>
    {phone && <div><h3 className="mb-1 text-meta font-semibold">Nel testo</h3><p className="rounded-lg border border-warning p-3">{item.context?.unit_content ?? issue.claim}</p></div>}
    <div ref={box}>
      <div className="mb-1 flex items-center justify-between gap-2"><h3 className="text-meta font-semibold">{paragraph ? 'Testo del paragrafo' : 'Correzione proposta'}</h3>
        {editing && <IconButton label="Ripristina la correzione proposta" icon={RotateCcw} disabled={!modified || busy} onClick={() => setText(proposed)} className="size-7 min-w-7" />}
      </div>
      {editing && !readOnly ? <Textarea id="review-edit" aria-label={paragraph ? 'Testo del paragrafo' : suggestion ? 'Testo corretto' : 'Correzione proposta'} autoFocus rows={1} value={text}
        ref={prepareInput}
        onChange={event => { setText(event.target.value); event.target.style.height = 'auto'; event.target.style.height = `${event.target.scrollHeight}px` }}
        onKeyDown={event => {
          if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelEdit() }
          else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); apply() }
        }} className="resize-none overflow-hidden border-accent-foreground bg-background" /> :
        <Tooltip content="Doppio clic per modificare" disabled={phone || readOnly || busy || cannotApply}>{trigger => <p {...trigger} data-testid="proposed-correction" className="cursor-text rounded-lg bg-muted p-3"
          onDoubleClick={() => { if (!busy && !readOnly && !cannotApply) onEditing(true) }} onClick={() => { if (phone && !busy && !readOnly && !cannotApply) onEditing(true) }}>{suggestion && !item.decision ? issue.suggested_fix : proposed}</p>}</Tooltip>}
    </div>
    {failure && <Alert tone="danger">{failure}</Alert>}
    <p className="text-meta">{issue.reason}</p>
    {issue.source_quote && <p className="border-l-2 pl-2 text-meta text-muted-foreground">Docente: {issue.source_quote}</p>}
    {issue.unanchored && <><Badge tone="warning">Non ancorata</Badge><p className="text-meta">La citazione non è stata trovata nel testo. {readOnly ? 'Il rifiuto è registrato.' : 'Puoi solo rifiutare questa issue.'}</p></>}
    {item.needs_reconfirmation && <><Badge tone="warning">Da riconfermare</Badge><p className="text-meta">La decisione precedente resta registrata. Puoi riconfermare la correzione se il passaggio è ritrovato oppure mantenere il testo attuale.</p></>}
    {changed && !issue.unanchored && <><Badge tone="warning">Testo cambiato</Badge><p className="text-meta">Il passaggio non si ritrova nel testo attuale. Puoi mantenerlo e chiudere l’issue.</p></>}
    {readOnly ? <div className="flex items-center justify-between gap-2"><Badge tone="success">{decisionLabels[item.decision!.decision]}</Badge><Button variant="ghost" size="sm" disabled={busy} onClick={onUndo}><Undo2 />Annulla</Button></div> : <div ref={controls} className="flex gap-2 max-md:[&_button]:h-12 max-md:[&_button]:min-w-12">
      {!cannotApply && (!suggestion || editing) && <IconButton label={editing && modified || suggestion ? 'Applica la tua correzione' : item.needs_reconfirmation ? 'Riconferma la correzione' : paragraph ? 'Accetta il testo' : 'Accetta la correzione'} icon={Check} variant="solid" disabled={busy || (editing && modified && !text.trim())} onClick={() => editing ? apply() : onDecide('accepted')} />}
      {paragraph && !cannotApply ? <IconButton label="Modifica il paragrafo" icon={Pencil} disabled={busy} onClick={() => onEditing(true)} /> : <IconButton label={issue.unanchored ? 'Rifiuta' : 'Mantieni il testo attuale'} icon={X} className="border" disabled={busy} onClick={() => { cancelEdit(); onDecide('rejected') }} />}
    </div>}
  </Card>
}
