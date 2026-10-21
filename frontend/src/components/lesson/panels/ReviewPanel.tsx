import { ASRSegments } from './ASRSegments'
import { ReviewUnits } from './ReviewUnits'
import { usePreference } from '@/lib/preferences'
import { IconButton } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { MathText } from '@/components/MathText'
import { Tooltip } from '@/components/ui/tooltip'
import { CheckCheck, Clock, TriangleAlert, Check, Eye, Headphones, MoreHorizontal, RotateCcw, ShieldCheck, Undo2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useSearchParams } from 'react-router'
import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useDecideIssue, useIssues, useRunJob, useUndoDecision, useReviewUnits } from '@/api/hooks'
import { useCancelJob, useJobs } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { parseIssueOrder, sortIssues } from '@/lib/issueOrder'
import { useIsPhone } from '@/lib/phone'
import { isActive } from '@/lib/jobs'
import { useLessonAudio } from '../audio'
import { decisionLabels, issueLabels, issueOf, paragraphIssue, type IssueItem } from '../reviewIssues'

export function ReviewPanel({ lesson: l, beforeAction = async () => undefined }: { lesson: Schemas['LessonDetail']; beforeAction?: () => Promise<void> }) {
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
  const [queuedUnits, setQueuedUnits] = useState<string[]>([])
  const [cardFailure, setCardFailure] = useState<{ id: string; message: string } | null>(null)
  // L'ultima decisione resta annullabile dall'intestazione anche quando l'avviso è sparito.
  // ids: le issue dell'ultima decisione (più di una dopo Accetta tutte).
  const [message, setMessage] = useState<{ ids: string[]; label: string; at: number } | null>(null)
  const [toast, setToast] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const phone = useIsPhone()
  const { seek } = useLessonAudio()
  const items = issues.data?.items ?? []
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
        const recorded = await decide.mutateAsync({ issueId: issueOf(selected).id, decision, text })
        const refreshed = await issues.refetch()
        const current = refreshed?.data?.items.find(item => issueOf(item).id === issueOf(selected).id)
        if (current?.needs_reconfirmation && recorded && current.decision?.timestamp === recorded.timestamp && current.decision?.decision === recorded.decision) {
          setCardFailure({ id: issueOf(selected).id, message: "La decisione non si applica: l'unità non c'è più." })
          setEditing(false)
          select(issueOf(selected).id)
          return
        }
        setCardFailure(null)
        setMessage({ ids: [issueOf(selected).id], label: `Correzione ${decisionLabels[decision]}.`, at: Date.now() })
        setToast(true)
      } catch (error) {
        const id = issueOf(selected).id
        setCardFailure({ id, message: errorMessage(error) })
        if (error instanceof ApiError && error.code === 'claim_changed') void issues.refetch()
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
  const verify = (unit?: string, force = false, skipPrefilter = false, includeExcluded = false) => {
    const list = unit ? [unit] : (force ? included : needsReview).map(u => u.unit_id)
    setQueuedUnits(list)
    void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', ...(unit ? { unit } : !force && list.length ? { units: list } : {}), ...(force ? { force: true } : {}), ...(skipPrefilter ? { skip_prefilter: true } : {}), ...(includeExcluded ? { include_excluded: true } : {}) })).finally(() => setQueuedUnits([]))
  }
  const orderedUnits = [...units].sort((a, b) => {
    if (order !== 'gravita') return 0
    const rank = (unit: string) => Math.min(3, ...pending.filter(item => issueOf(item).unit_id === unit).map(item => { const value = ['high', 'medium', 'low'].indexOf(issueOf(item).severity); return value < 0 ? 3 : value }))
    return rank(a.unit_id) - rank(b.unit_id)
  })
  const unitOf = (id: string) => { const item = items.find(row => issueOf(row).id === id); return item ? issueOf(item).unit_id : null }
  const undoBusy = message ? message.ids.some(id => decisionBusy(unitOf(id))) : busy
  // Il backend annulla una issue alla volta: dopo Accetta tutte si annullano tutte, dall'ultima.
  const undoLast = () => {
    if (!message) return
    void action(async () => {
      const ids = [...message.ids]
      while (ids.length) { await undo.mutateAsync(ids.at(-1)!); ids.pop() }
      select(message.ids[0]); setMessage(null); setToast(false)
    })
  }
  // Accetta tutte: solo le correzioni applicabili così come sono (niente avvisi di paragrafo, testi cambiati, citazioni non ancorate o soli suggerimenti).
  const acceptable = pending.filter(item => {
    const issue = issueOf(item)
    if (paragraphIssue(issue) || item.quote_status === 'changed' || issue.unanchored) return false
    if (item.fix_text === null && !item.decision?.resolved_text) return false
    return !(verifying && pendingUnits.includes(issue.unit_id ?? ''))
  })
  const acceptAll = () => {
    setConfirmAll(false)
    const ids = acceptable.map(item => issueOf(item).id)
    void action(async () => {
      const done: string[] = []
      try {
        for (const id of ids) { await decide.mutateAsync({ issueId: id, decision: 'accepted' }); done.push(id) }
      } finally {
        if (done.length) {
          setCardFailure(null); setEditing(false)
          setMessage({ ids: done, label: done.length === 1 ? 'Correzione accettata.' : `${done.length} correzioni accettate.`, at: Date.now() })
          setToast(true)
          const next = pending.find(item => !done.includes(issueOf(item).id))
          const query = new URLSearchParams(params)
          query.delete('review_unit')
          if (next) query.set('issue', issueOf(next).id); else query.delete('issue')
          setParams(query, { replace: true })
        }
      }
    })
  }
  const verifyUnavailable = reviewUnits.isPending ? 'Carico le unità' : reviewUnits.isError ? 'Stato delle unità non disponibile' : busy ? 'Lavorazione in corso' : l.phases.rewrite !== 'VALID' ? 'Rielaborazione non pronta' : needsReview.length === 0 ? 'Tutte le unità sono verificate' : null
  if (issues.isPending) return <p className="text-meta text-muted-foreground">Carico la verifica…</p>
  if (issues.isError) return <Alert tone="danger">{errorMessage(issues.error)}</Alert>
  return <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="font-semibold" role="status">{verifying ? 'In corso · ' : ''}{status} · {reviewedCount}/{included.length} unità verificate</p>
      <div className="flex items-center gap-1">
        <IconButton label="Verifica" icon={ShieldCheck} variant="solid" unavailable={verifyUnavailable} hint={`${needsReview.length} unità da verificare`} badge={needsReview.length ? <span className="absolute -right-1 -top-1 rounded-full bg-foreground px-1 text-meta text-background">{needsReview.length}</span> : undefined} onClick={() => verify()} />
        <IconButton label="Ordine delle issue" icon={order === 'cronologico' ? Clock : TriangleAlert} hint={order === 'cronologico' ? 'Cronologico' : 'Gravità'} onClick={() => { const nextOrder = order === 'cronologico' ? 'gravita' : 'cronologico'; setSavedOrder(nextOrder); const next = new URLSearchParams(params); next.set('ordine', nextOrder); setParams(next, { replace: true }) }} />
        <IconButton label="Mostra decise" icon={Eye} active={showDecided} aria-pressed={showDecided} onClick={() => setShowDecided(!showDecided)} />
        <IconButton label={`Accetta tutte le correzioni da decidere (${acceptable.length})`} icon={CheckCheck} unavailable={busy ? 'Lavorazione in corso' : acceptable.length === 0 ? 'Nessuna correzione da accettare' : null} onClick={() => setConfirmAll(true)} />
        <IconButton label="Annulla l'ultima decisione" icon={Undo2} unavailable={!message ? 'Nessuna decisione da annullare' : undoBusy ? 'Lavorazione in corso' : null} hint={message?.label} onClick={undoLast} />
        <LinkMenuButton label="Azioni della verifica" icon={MoreHorizontal} unavailable={busy ? 'Lavorazione in corso' : undefined} items={[
          { label: 'Riesegui tutta la lezione', unavailable: l.review_progress?.completed_once ? null : 'Una verifica completa non è ancora finita', onSelect: () => verify(undefined, true) },
          { label: 'Esegui senza classificatore', unavailable: l.phases.rewrite !== 'VALID' ? 'Rielaborazione non pronta' : included.length === 0 ? 'Nessuna unità da verificare' : null, onSelect: () => verify(undefined, true, true) },
        ]} />
      </div>
    </div>
    <p className="text-meta text-muted-foreground" data-testid="documents-status">{l.phases.build === 'VALID' && !documentsUpdating ? 'Documento aggiornato' : 'Documento in aggiornamento'}{units.some(u => u.state === 'excluded') ? ` · ${units.filter(u => u.state === 'excluded').length} escluse` : ''}</p>
    {verifying && <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(active!.id)}>Interrompi</Button>}
    {reviewUnits.isError && <Alert tone="danger">{errorMessage(reviewUnits.error)}</Alert>}
    {complete && !showDecided ? <Card data-testid="review-summary" className="flex flex-col gap-2 p-4 text-meta"><Check className="size-6 text-success" /><p className="font-semibold">La verifica è tutta decisa.</p><p>{ordered.filter(item => item.decision?.decision === 'accepted').length} accettate · {ordered.filter(item => item.decision?.decision === 'edited').length} modificate · {ordered.filter(item => item.decision?.decision === 'rejected').length} mantenute</p></Card> : <ReviewUnits units={orderedUnits} busy={busy} running={runningUnits} queued={waitingUnits} missing={units.filter(unit => !(reviewUnits.data ?? []).some(row => row.unit_id === unit.unit_id)).map(unit => unit.unit_id)} selectedUnit={(selected ? issueOf(selected).unit_id : null) ?? params.get('review_unit')} items={ordered.filter(item => !item.decision || item.needs_reconfirmation || showDecided)} onVerify={unit => verify(unit)} onReverify={unit => verify(unit, true)} onBypass={(unit, excluded) => verify(unit, true, true, excluded)} onClassifier={() => { const next = new URLSearchParams(params); next.set('panel', 'classificatore'); next.delete('issue'); next.delete('review_unit'); setParams(next) }} renderIssues={unit => <ul aria-label={`Issue dell’unità ${unit}`} className="flex flex-col gap-1">
      {ordered.filter(item => issueOf(item).unit_id === unit && (!item.decision || item.needs_reconfirmation || showDecided)).map(item => <li key={issueOf(item).id}>{selected === item ? <IssueCard key={`${issueOf(item).id}:${item.decision?.timestamp}:${item.needs_reconfirmation}`} item={item} busy={decisionBusy(issueOf(item).unit_id)} editing={editing} onEditing={setEditing} onDecide={onDecide} onSeek={l.has_audio ? seek : undefined} phone={phone} failure={cardFailure?.id === issueOf(item).id ? cardFailure.message : undefined} changed={item.quote_status === 'changed'} onReverify={() => verify(issueOf(item).unit_id ?? undefined, true)} onUndo={() => void action(async () => { await undo.mutateAsync(issueOf(item).id); if (message?.ids.includes(issueOf(item).id)) { const rest = message.ids.filter(id => id !== issueOf(item).id); setMessage(rest.length ? { ...message, ids: rest } : null); if (!rest.length) setToast(false) } select(issueOf(item).id) })} /> : <Button variant="ghost" className="h-auto w-full flex-col items-start whitespace-normal py-2 text-left text-meta" aria-current={selected === item ? 'true' : undefined} onClick={() => select(issueOf(item).id)}><span>{issueLabels[issueOf(item).type]} · {item.context?.timecode}</span><span className="line-clamp-2 text-muted-foreground"><MathText text={item.decision?.resolved_text ?? issueOf(item).suggested_fix ?? issueOf(item).claim} /></span>{item.decision && <span>{item.needs_reconfirmation ? 'Da riconfermare' : decisionLabels[item.decision.decision]}</span>}</Button>}</li>)}
    </ul>} />}
    <ConfirmDialog open={confirmAll} title="Accetta tutte le correzioni" confirmLabel={`Accetta ${acceptable.length}`} confirmDisabled={busy || acceptable.length === 0} onConfirm={acceptAll} onCancel={() => setConfirmAll(false)}>
      <p>Accetti {acceptable.length === 1 ? 'la correzione proposta' : `le ${acceptable.length} correzioni proposte`} ancora da decidere. Avvisi di paragrafo, testi cambiati e soli suggerimenti restano da decidere a mano. Puoi annullare tutto con Annulla l'ultima decisione.</p>
    </ConfirmDialog>
    {message && toast && <DecisionToast key={message.at} label={message.label} busy={undoBusy} onUndo={undoLast} onClose={() => setToast(false)} />}
    {(failure || cancel.isError) && <Alert tone="danger">{failure ?? errorMessage(cancel.error)}</Alert>}
  </div>
}

function IssueCard({ item, failure, busy, editing, onEditing, onDecide, onSeek, phone, changed, onUndo, onReverify }: {
  failure?: string; phone: boolean; changed: boolean; onUndo: () => void; onReverify: () => void
  item: IssueItem; busy: boolean; editing: boolean; onEditing: (value: boolean) => void
  onDecide: (decision: 'accepted' | 'rejected' | 'edited', text?: string) => void; onSeek?: (seconds: number, play?: boolean, endSeconds?: number) => void
}) {
  const issue = issueOf(item)
  const paragraph = paragraphIssue(issue)
  const suggestion = !paragraph && item.fix_text === null && !item.decision?.resolved_text
  const readOnly = !!item.decision && !item.needs_reconfirmation
  const proposed = item.decision?.resolved_text ?? (paragraph ? item.context?.unit_content ?? issue.claim : suggestion ? issue.claim : item.fix_text ?? issue.suggested_fix ?? issue.claim)
  const cannotApply = !paragraph && (changed || !!issue.unanchored)
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
  const listen = !paragraph && !readOnly && onSeek && item.context?.start_s != null ? <IconButton label={`Ascolta da ${item.context.timecode}`} icon={Headphones} className="border" onClick={() => onSeek(item.context!.start_s!)} /> : null
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
  return <Card className="flex min-w-0 flex-col gap-3 p-3 [overflow-wrap:anywhere]" data-testid="issue-detail">
    <div className="flex flex-wrap items-center gap-2"><b>{issueLabels[issue.type] ?? issue.type}</b><Badge tone={issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'neutral'}>{({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issue.severity] ?? issue.severity}</Badge></div>
    {phone && !paragraph && <div><h3 className="mb-1 text-meta font-semibold">Nel testo</h3><p className="min-w-0 rounded-lg border border-warning p-3 [overflow-wrap:anywhere]"><MathText text={item.context?.unit_content ?? issue.claim} /></p></div>}
    {issue.type === 'ERR_ASR_ST' && <ASRSegments segments={item.context?.asr_segments ?? [{ segment_id: issue.segment_id ?? '', text_raw: issue.claim, start_s: item.context?.start_s, end_s: item.context?.end_s }]} onSeek={!readOnly ? onSeek : undefined} />}
    {!paragraph && <div ref={box}>
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
        <Tooltip content="Doppio clic per modificare" disabled={phone || readOnly || busy || cannotApply}>{trigger => <p {...trigger} data-testid="proposed-correction" className="min-w-0 cursor-text rounded-lg bg-muted p-3 [overflow-wrap:anywhere]"
          onDoubleClick={() => { if (!busy && !readOnly && !cannotApply) onEditing(true) }} onClick={() => { if (phone && !busy && !readOnly && !cannotApply) onEditing(true) }}>{changed ? <s><MathText text={issue.claim} /></s> : <MathText text={suggestion && !item.decision ? (issue.suggested_fix ?? '') : proposed} />}</p>}</Tooltip>}
    </div>}
    {failure && <Alert tone="danger">{failure}</Alert>}
    <p className="min-w-0 text-meta [overflow-wrap:anywhere]"><MathText text={issue.reason} /></p>
    {issue.source_quote && <p className="min-w-0 border-l-2 pl-2 text-meta text-muted-foreground [overflow-wrap:anywhere]">Docente: <MathText text={issue.source_quote} /></p>}
    {issue.unanchored && <><Badge tone="warning">Non ancorata</Badge><p className="text-meta">La citazione non è stata trovata nel testo. {readOnly ? 'Il rifiuto è registrato.' : 'Puoi solo rifiutare questa issue.'}</p></>}
    {item.needs_reconfirmation && <><Badge tone="warning">Da riconfermare</Badge><p className="text-meta">La decisione precedente resta registrata. Puoi riconfermare la correzione se il passaggio è ritrovato oppure mantenere il testo attuale.</p></>}
    {changed && !paragraph && <><Badge tone="warning">Testo cambiato</Badge><p className="text-meta">Il passaggio non si ritrova nel testo attuale. Puoi mantenerlo e chiudere l’issue.</p></>}
    {readOnly ? <div className="flex items-center justify-between gap-2"><Badge tone="success">{decisionLabels[item.decision!.decision]}</Badge><Button variant="ghost" size="sm" disabled={busy} onClick={onUndo}><Undo2 />Annulla</Button></div> : changed && !paragraph ? <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide('rejected')}>Chiudi</Button>
      {issue.unit_id && <Button size="sm" variant="outline" disabled={busy} onClick={onReverify}>Verifica di nuovo l'unità</Button>}
      {listen}
    </div> : <div ref={controls} className="flex gap-2 max-md:[&_button]:h-12 max-md:[&_button]:min-w-12">
      {paragraph ? <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide('accepted')}><Check />Ho controllato</Button> : !cannotApply && (!suggestion || editing) && <IconButton label={editing && modified || suggestion ? 'Applica la tua correzione' : item.needs_reconfirmation ? 'Riconferma la correzione' : paragraph ? 'Accetta il testo' : 'Accetta la correzione'} icon={Check} variant="solid" disabled={busy || (editing && modified && !text.trim())} onClick={() => editing ? apply() : onDecide('accepted')} />}
      {!paragraph && <IconButton label={issue.unanchored ? 'Rifiuta' : 'Mantieni il testo attuale'} icon={X} className="border" disabled={busy} onClick={() => { cancelEdit(); onDecide('rejected') }} />}
      {listen}
    </div>}
  </Card>
}

const TOAST_MS = 5000

/** Avviso della decisione: sale dal basso sopra pannello e barra audio, si chiude dopo 5 s (in pausa al passaggio o al focus). */
function DecisionToast({ label, busy, onUndo, onClose }: { label: string; busy: boolean; onUndo: () => void; onClose: () => void }) {
  const remaining = useRef(TOAST_MS)
  const started = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })
  const resume = useCallback(() => {
    clearTimeout(timer.current)
    started.current = Date.now()
    timer.current = setTimeout(() => close.current(), remaining.current)
  }, [])
  const pause = () => {
    if (timer.current === undefined) return
    clearTimeout(timer.current)
    timer.current = undefined
    remaining.current = Math.max(0, remaining.current - (Date.now() - started.current))
  }
  useEffect(() => { resume(); return () => clearTimeout(timer.current) }, [resume])
  return createPortal(<div role="log" aria-live="polite" data-testid="review-decision-message"
    onMouseEnter={pause} onMouseLeave={event => { if (!event.currentTarget.contains(document.activeElement)) resume() }} onFocus={pause} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) resume() }}
    style={{ '--rt-toast-duration': `${TOAST_MS}ms` } as CSSProperties}
    className="rt-toast fixed bottom-[calc(88px+env(safe-area-inset-bottom))] left-1/2 z-50 w-max max-w-[calc(100vw-32px)] -translate-x-1/2 overflow-hidden rounded-lg bg-foreground text-meta text-background shadow-panel md:bottom-6 md:left-auto md:right-[calc(var(--rt-panel-width)/2+4px)] md:max-w-[calc(var(--rt-panel-width)-40px)] md:translate-x-1/2">
    <div className="flex items-center gap-3 py-1.5 pl-4 pr-1.5">
      <span>{label}</span>
      <Button variant="ghost" size="sm" className="text-background hover:bg-background/15 hover:text-background" disabled={busy} onClick={onUndo}><Undo2 />Annulla</Button>
    </div>
    <div aria-hidden className="rt-toast-timer h-0.5 bg-background/60" data-testid="review-decision-timer" />
  </div>, document.body)
}
