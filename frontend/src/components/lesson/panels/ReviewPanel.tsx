import { useRelevance } from '@/api/relevance'
import { ReviewUnits } from './ReviewUnits'
import { ConfirmDialog } from '@/components/ui/dialog'
import { usePreference } from '@/lib/preferences'
import { UnitStrip } from './UnitStrip'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { EditorState } from '@codemirror/state'
import { ListTree, Check, RotateCcw, Pencil, ShieldCheck, Undo2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useDecideIssue, useDecisions, useIssues, useRunJob, useUndoDecision, useReviewUnits } from '@/api/hooks'
import { useCancelJob, useJobs } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ISSUE_ORDERS, parseIssueOrder, sortIssues } from '@/lib/issueOrder'
import { phaseProgress } from '@/lib/progress'
import { useIsPhone } from '@/lib/phone'
import { issueRange } from '../lessonReview'
import { isActive } from '@/lib/jobs'
import { useLessonAudio } from '../audio'
import { decisionLabels, issueLabels, issueOf, paragraphIssue, type IssueItem } from '../reviewIssues'

export function ReviewPanel({ lesson: l, beforeAction = async () => undefined, markdown }: { markdown?: string; lesson: Schemas['LessonDetail']; beforeAction?: () => Promise<void> }) {
  const relevance = useRelevance(l.id)
  const issues = useIssues(l.id)
  const reviewUnits = useReviewUnits(l.id)
  const units = reviewUnits.data ?? []
  const [byUnit, setByUnit] = usePreference('review.by-unit', false)
  const [savedOrder, setSavedOrder] = usePreference('review.order', 'cronologico')
  const [confirmReview, setConfirmReview] = useState(false)
  const [confirmUnit, setConfirmUnit] = useState<string | null>(null)
  const [queuedUnits, setQueuedUnits] = useState<string[]>([])
  const [selectedUnits, setSelectedUnits] = useState<string[]>([])
  const [changedIssues, setChangedIssues] = useState<string[]>([])
  const [cardFailure, setCardFailure] = useState<{ id: string; message: string } | null>(null)
  const decisions = useDecisions(l.id)
  const jobs = useJobs({ lesson_id: l.id, limit: 20 })
  const run = useRunJob(l.id)
  const cancel = useCancelJob()
  const decide = useDecideIssue(l.id)
  const undo = useUndoDecision(l.id)
  const [params, setParams] = useSearchParams()
  const [group, setGroup] = useState<'pending' | 'decided' | 'units'>('pending')
  const phone = useIsPhone()
  const [showList, setShowList] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const { seek } = useLessonAudio()
  const items = issues.data?.items ?? []
  const order = parseIssueOrder(params.get('ordine') ?? savedOrder)
  const ordered = sortIssues(items, order, (item) => ({ ...issueOf(item), startSeconds: item.context?.start_s }))
  const unitFilter = params.get('review_unit')
  const allPending = ordered.filter((i) => !i.decision)
  const allDecided = ordered.filter((i) => i.decision)
  const pending = allPending.filter(i => !unitFilter || issueOf(i).unit_id === unitFilter)
  const decided = allDecided.filter(i => !unitFilter || issueOf(i).unit_id === unitFilter)
  const needsReview = units.filter(u => ['never', 'changed', 'failed'].includes(u.state))
  const reviewedCount = units.filter(u => ['ok', 'issues'].includes(u.state)).length

  const selected = items.find((i) => issueOf(i).id === params.get('issue') && (!unitFilter || issueOf(i).unit_id === unitFilter)) ?? pending[0]
  const last = [...(decisions.data ?? [])].filter((d) => items.some((i) => issueOf(i).id === d.issue_id)).sort((a, b) => a.timestamp.localeCompare(b.timestamp)).pop()
  const active = jobs.data?.find((j) => j.type !== 'documents' && isActive(j.state))
  const verifying = active && (active.type === 'run_pipeline' || active.type === 'run_phase') && (active.progress?.phase === 'review' || (active.payload as { phase?: string })?.phase === 'review')
  const progress = verifying ? phaseProgress(active) : null
  const waiting = jobs.data?.some((j) => j.state === 'waiting_for_decision' && j.decision?.kind === 'science_issue')
  const complete = l.phases.review === 'VALID'
  const partial = l.phases.review === 'PARTIAL'
  const stale = l.phases.review === 'STALE'
  const done = complete || partial || stale || items.length > 0 || units.length > 0
  const busy = saving || decide.isPending || undo.isPending || run.isPending || !!active
  const select = (id: string) => { setEditing(false); const next = new URLSearchParams(params); next.set('issue', id); setParams(next, { replace: true }) }
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
      } catch (error) {
        const id = issueOf(selected).id
        setCardFailure({ id, message: errorMessage(error) })
        if (error instanceof ApiError && error.code === 'claim_changed') setChangedIssues(old => [...old, id])
        return
      }
      setEditing(false)
      const next = pending.find((i) => issueOf(i).id !== issueOf(selected).id)
      const query = new URLSearchParams(params)
      if (next) query.set('issue', issueOf(next).id); else query.delete('issue')
      setParams(query, { replace: true })
    })
  }
  const verify = (force: boolean) => void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', ...(force ? { force: true } : {}) }))
  const verifyUnit = (unit: string, force = false) => {
    setQueuedUnits([unit])
    void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', unit, ...(force ? { force: true } : {}) })).finally(() => setQueuedUnits([]))
  }
  const verifyUnits = (list: string[]) => {
    if (list.length === 1) { verifyUnit(list[0]); return }
    setQueuedUnits(list)
    void action(() => run.mutateAsync({ type: 'run_phase', phase: 'review', units: list })).finally(() => setQueuedUnits([]))
  }
  // Le unità da verificare vengono dal registro; senza registro (lezioni vecchie) riprende la run parziale.
  const missingCount = needsReview.length || (partial ? Math.max((l.review_progress?.total ?? 0) - (l.review_progress?.reviewed ?? 0), 0) : 0)
  const verifyMissing = () => { if (needsReview.length) verifyUnits(needsReview.map(u => u.unit_id)); else verify(false) }
  const selectable = needsReview.map(u => u.unit_id)
  const chosen = selectedUnits.filter(id => selectable.includes(id))
  const filterUnit = (unit: string) => {
    setGroup('pending'); setShowList(true)
    const next = new URLSearchParams(params); next.set('review_unit', unit); next.delete('issue'); setParams(next, { replace: true })
  }
  const reviewPayload = active?.payload as { units?: string[]; unit?: string } | undefined
  const runningUnits = active?.type === 'review_unit' || verifying
    ? reviewPayload?.units ?? (reviewPayload?.unit ? [reviewPayload.unit] : units.map(u => u.unit_id))
    : []
  const visible = group === 'pending' ? pending : decided
  const grouped = Array.from(new Set(visible.map(i => issueOf(i).unit_id ?? ''))).map(id => ({
    id, title: units.find(u => u.unit_id === id)?.title ?? items.find(i => issueOf(i).unit_id === id)?.context?.unit_info?.split(' - ').slice(1).join(' - ') ?? '',
    items: visible.filter(i => (issueOf(i).unit_id ?? '') === id),
    all: items.filter(i => (issueOf(i).unit_id ?? '') === id),
  })).sort((a,b) => {
    if (order === 'gravita') {
      const severity = (group: typeof a) => Math.min(...group.items.map(i => ['high','medium','low'].indexOf(issueOf(i).severity)))
      const rank = severity(a) - severity(b)
      if (rank) return rank
    }
    const index = (id: string) => { const i = units.findIndex(u => u.unit_id === id); return i < 0 ? Number.MAX_SAFE_INTEGER : i }
    return index(a.id) - index(b.id) || a.id.localeCompare(b.id, 'it', { numeric: true })
  })
  const issueList = (list: IssueItem[]) => list.map(item => { const issue = issueOf(item); return <li key={issue.id}>
    <Button variant="ghost" className="h-auto w-full flex-col items-start whitespace-normal py-2 text-left text-meta" aria-current={selected === item ? 'true' : undefined} onClick={() => select(issue.id)}>
      <span>{issueLabels[issue.type] ?? issue.type} · {item.context?.timecode ?? issue.unit_id}</span>
      <span className="line-clamp-2 text-muted-foreground">{issue.claim}</span>
    </Button>
  </li> })
  if (issues.isPending) return <p className="text-meta text-muted-foreground">Carico la verifica…</p>
  if (issues.isError) return <Alert tone="danger">{errorMessage(issues.error)}</Alert>
  return <div className="flex flex-col gap-3 text-body" data-testid="lesson-review-panel">
    <p className="font-semibold" role="status">{verifying ? 'In corso' : partial ? `Verificate ${l.review_progress?.reviewed ?? 0} unità su ${l.review_progress?.total ?? l.unit_count ?? 0}` : stale ? 'Il testo è cambiato dopo la verifica' : complete ? allPending.length ? `${allPending.length} da decidere su ${items.length}` : 'Tutte decise' : 'Mai verificata'}</p>
    <p className="text-meta text-muted-foreground">{reviewedCount} unità verificate su {units.length} · {units.filter(u => u.state === 'ok').length} senza problemi</p>
    {reviewUnits.isError && <Alert tone="danger">{errorMessage(reviewUnits.error)}</Alert>}
    {verifying && <>
      <p className="text-meta text-muted-foreground">{progress?.detail ? `${progress.detail} · ` : ''}{items.length} issue trovate finora</p>
      <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(active.id)}>Interrompi</Button>
    </>}
    {!verifying && !stale && done && missingCount > 0 && <Button disabled={busy} onClick={verifyMissing}>Verifica le unità mancanti ({missingCount})</Button>}
    {!verifying && stale && <>
      <p className="text-meta text-muted-foreground">Le correzioni fatte a mano non rifanno la verifica.</p>
      <Button disabled={busy} onClick={() => void action(() => run.mutateAsync({ type: 'run_pipeline', with_review: true }))}>Aggiorna il documento</Button>
    </>}
    {!verifying && complete && allPending.length === 0 && <p className="text-meta">{decided.length} issue decise: {['accepted', 'rejected', 'edited'].map((d) => `${decided.filter((i) => i.decision?.decision === d).length} ${decisionLabels[d] === 'accettata' ? 'accettate' : d === 'rejected' ? 'mantenute' : 'modificate'}`).join(', ')}.</p>}
    <p className="text-meta text-muted-foreground" data-testid="documents-status">{l.phases.build === 'VALID' ? 'Documento aggiornato' : 'Documento in aggiornamento'}</p>
    {waiting && <Badge tone="neutral">Pipeline in attesa</Badge>}
    {last && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void action(async () => { await undo.mutateAsync(last.issue_id); select(last.issue_id) })}><Undo2 />Annulla l'ultima</Button>}
    {group !== 'units' && selected && <IssueCard key={issueOf(selected).id} item={selected} busy={busy} editing={editing} onEditing={setEditing} onDecide={onDecide} onSeek={l.has_audio ? seek : undefined} phone={phone} failure={cardFailure?.id === issueOf(selected).id ? cardFailure.message : undefined} changed={changedIssues.includes(issueOf(selected).id) || markdown !== undefined && !selected.decision && !issueRange(EditorState.create({ doc: markdown }), selected)} onCloseIssue={() => onDecide(paragraphIssue(issueOf(selected)) ? 'accepted' : 'rejected')} onRecheck={() => setConfirmUnit(issueOf(selected).unit_id ?? null)} />}
    {phone && done && <Button variant="outline" size="sm" aria-expanded={showList} onClick={() => setShowList(!showList)}>Elenco ({items.length})</Button>}
    {done && (!phone || showList) && <>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={group === 'pending' ? 'default' : 'outline'} aria-pressed={group === 'pending'} onClick={() => setGroup('pending')}>Da decidere {allPending.length}</Button>
        <Button size="sm" variant={group === 'decided' ? 'default' : 'outline'} aria-pressed={group === 'decided'} onClick={() => setGroup('decided')}>Decise {allDecided.length}</Button>
        <Button size="sm" variant={group === 'units' ? 'default' : 'outline'} aria-pressed={group === 'units'} onClick={() => setGroup('units')}>Unità {units.length}</Button>
      </div>
      {group === 'units' ? <>
        {chosen.length > 0 && <Button size="sm" disabled={busy} onClick={() => { verifyUnits(chosen); setSelectedUnits([]) }}><ShieldCheck />Verifica le selezionate ({chosen.length})</Button>}
        <ReviewUnits units={units} busy={busy} running={[...runningUnits, ...queuedUnits]} selected={chosen} onSelect={(id, on) => setSelectedUnits(old => on ? [...old, id] : old.filter(x => x !== id))} onVerify={verifyUnit} onReverify={setConfirmUnit} onFilter={filterUnit} />
      </> : <>
        {unitFilter && <div data-testid="review-unit-filter" className="flex items-center justify-between rounded-lg bg-muted px-3 py-1 text-meta"><span>Unità {unitFilter}</span><IconButton label="Togli il filtro per unità" icon={X} onClick={() => { const next = new URLSearchParams(params); next.delete('review_unit'); setParams(next, { replace: true }) }} /></div>}
        <div className="flex gap-2"><Select aria-label="Ordine delle issue" value={order} onChange={(e) => { const next = new URLSearchParams(params); next.set('ordine', e.target.value); setSavedOrder(e.target.value); setParams(next, { replace: true }) }}>{ISSUE_ORDERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
          <Button size="sm" variant={byUnit ? 'default' : 'outline'} aria-pressed={byUnit} onClick={() => setByUnit(!byUnit)}><ListTree />Per unità</Button>
        </div>
        {byUnit ? grouped.map(g => <details key={g.id} open data-testid="review-issue-group" data-unit={g.id} className="border-t pt-2">
          <summary className="cursor-pointer text-meta"><b>{g.id}</b> {g.title} <span className="inline-flex gap-1" aria-hidden>{g.all.map(i => <span key={issueOf(i).id} className={`inline-block size-1.5 rounded-full ${issueOf(i).severity === 'high' ? 'bg-danger' : issueOf(i).severity === 'medium' ? 'bg-warning' : 'bg-muted-foreground'}`} />)}</span>
            <span className="ml-2 text-muted-foreground">{g.all.filter(i => !i.decision).length} da decidere · {g.all.filter(i => i.decision).length} decise</span>
          </summary><ul className="flex flex-col gap-1">{issueList(g.items)}</ul>
        </details>) : <ul aria-label={group === 'pending' ? 'Da decidere' : 'Decise'} className="flex flex-col gap-1">{issueList(visible)}</ul>}
      </>}
    </>}
    <Button variant={done ? 'outline' : 'default'} size="sm" disabled={busy || l.phases.rewrite !== 'VALID'} onClick={() => { if (done) setConfirmReview(true); else verify(false) }}><ShieldCheck />{done ? 'Verifica di nuovo tutta la lezione' : 'Verifica tutta la lezione'}</Button>
    <ConfirmDialog open={confirmReview} title="Verifica di nuovo tutta la lezione" confirmLabel="Verifica tutte le unità" confirmDisabled={busy} onCancel={() => setConfirmReview(false)} onConfirm={() => { setConfirmReview(false); verify(true) }}>
      <div className="flex flex-col gap-2 text-body">
        <p>Rifà la verifica di tutte le unità, anche di quelle già verificate.</p>
        {allDecided.length > 0 && <p className="text-meta text-muted-foreground">{allDecided.length} decisioni potrebbero sparire se le issue non si ritrovano</p>}
      </div>
    </ConfirmDialog>
    <ConfirmDialog open={confirmUnit !== null} title={`Verifica di nuovo l'unità ${confirmUnit ?? ''}`} confirmLabel="Verifica di nuovo" confirmDisabled={busy} onCancel={() => setConfirmUnit(null)} onConfirm={() => { if (confirmUnit) verifyUnit(confirmUnit, true); setConfirmUnit(null) }}>
      Le decisioni prese restano agganciate alle issue ritrovate
    </ConfirmDialog>
    {relevance.data && <UnitStrip target="revisore"
      units={relevance.data.units.map(unit => ({ unit_id: unit.unit_id, title: unit.title, included: unit.review_included, unclassified: relevance.data.mode !== 'disabled' && (unit.stale || !unit.prediction) }))}
      rule={relevance.data.mode === 'disabled' ? 'Classificatore spento: al revisore vanno tutte le unità' : `Al revisore vanno le unità didattiche secondo il classificatore${relevance.data.units.some(u => u.stale || !u.prediction) ? ', più quelle non ancora classificate' : ''}`}
      classifierEnabled={relevance.data.mode !== 'disabled'} classifierUpdated={!!relevance.data.summary && relevance.data.summary.missing + relevance.data.summary.stale + relevance.data.summary.errors === 0}
      onSelect={() => { const next = new URLSearchParams(params); next.set('panel', 'classificatore'); next.delete('issue'); setParams(next) }} />}
    {(failure || cancel.isError) && <Alert tone="danger">{failure ?? errorMessage(cancel.error)}</Alert>}
  </div>
}

function IssueCard({ item, failure, busy, editing, onEditing, onDecide, onSeek, phone, changed, onCloseIssue, onRecheck }: {
  failure?: string; phone: boolean; changed: boolean; onCloseIssue: () => void; onRecheck: () => void
  item: IssueItem; busy: boolean; editing: boolean; onEditing: (value: boolean) => void
  onDecide: (decision: 'accepted' | 'rejected' | 'edited', text?: string) => void; onSeek?: (seconds: number) => void
}) {
  const issue = issueOf(item)
  const paragraph = paragraphIssue(issue)
  const suggestion = !paragraph && item.fix_text === null
  const proposed = paragraph ? item.context?.unit_content ?? issue.claim : suggestion ? issue.claim : item.fix_text ?? issue.suggested_fix ?? issue.claim
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
    if (!editing || paragraph) return
    const outside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node) && !controls.current?.contains(event.target as Node)) apply()
    }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [editing, paragraph, modified, text, busy]) // oxlint-disable-line react-hooks/exhaustive-deps
  return <Card className="flex flex-col gap-3 p-3" data-testid="issue-detail">
    <div className="flex flex-wrap items-center gap-2"><b>{issueLabels[issue.type] ?? issue.type}</b><Badge tone={issue.severity === 'high' ? 'danger' : issue.severity === 'medium' ? 'warning' : 'neutral'}>{({ high: 'alta', medium: 'media', low: 'bassa' } as Record<string, string>)[issue.severity] ?? issue.severity}</Badge></div>
    <div className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground"><span>Unità {issue.unit_id}</span>{onSeek && item.context?.start_s != null && <Button size="sm" variant="link" onClick={() => onSeek(item.context!.start_s!)}>Ascolta da {item.context.timecode}</Button>}</div>
    {phone && <div><h3 className="mb-1 text-meta font-semibold">Nel testo</h3><p className="rounded-lg border border-warning p-3">{item.context?.unit_content ?? issue.claim}</p></div>}
    {!paragraph && !changed && !issue.unanchored && <div ref={box}>
      <div className="mb-1 flex items-center justify-between gap-2"><h3 className="text-meta font-semibold">{suggestion ? 'Suggerimento' : 'Correzione proposta'}</h3>
        {editing && <IconButton label="Ripristina la correzione proposta" icon={RotateCcw} disabled={!modified || busy} onClick={() => setText(proposed)} className="size-7 min-w-7" />}
      </div>
      {editing ? <Textarea id="review-edit" aria-label={suggestion ? 'Testo corretto' : 'Correzione proposta'} autoFocus rows={1} value={text}
        ref={prepareInput}
        onChange={event => { setText(event.target.value); event.target.style.height = 'auto'; event.target.style.height = `${event.target.scrollHeight}px` }}
        onKeyDown={event => {
          if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelEdit() }
          else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); apply() }
        }} className="resize-none overflow-hidden border-accent-foreground bg-background" /> :
        <Tooltip content="Doppio clic per modificare" disabled={phone || !!item.decision || busy}>{trigger => <p {...trigger} data-testid="proposed-correction" className="cursor-text rounded-lg bg-muted p-3"
          onDoubleClick={() => { if (!busy && !item.decision) onEditing(true) }} onClick={() => { if (phone && !busy && !item.decision) onEditing(true) }}>{suggestion ? issue.suggested_fix : proposed}</p>}</Tooltip>}
    </div>}
    {failure && <Alert tone="danger">{failure}</Alert>}
    <p className="text-meta">{issue.reason}</p>
    {issue.source_quote && <p className="border-l-2 pl-2 text-meta text-muted-foreground">Docente: {issue.source_quote}</p>}
    {issue.unanchored && <><Badge tone="warning">Non ancorata</Badge><p className="text-meta">La citazione non è stata trovata nel testo. Puoi solo rifiutare questa issue.</p></>}
    {changed && !issue.unanchored && <>
      <Badge tone="warning">Testo cambiato</Badge>
      <p className="text-meta text-muted-foreground line-through">{issue.claim}</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={onCloseIssue}>Chiudi l'issue</Button><Button size="sm" variant="outline" disabled={busy || !issue.unit_id} onClick={onRecheck}>Verifica di nuovo l'unità {issue.unit_id}</Button></div>
    </>}
    {item.decision ? <Badge tone="success">{decisionLabels[item.decision.decision]}</Badge> : issue.unanchored ? <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide('rejected')}>Rifiuta</Button> : paragraph && editing ? <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); onDecide('edited', text) }}>
      <label htmlFor="review-edit" className="text-meta">{paragraph ? 'Testo del paragrafo' : 'Testo corretto'}</label>
      <Textarea id="review-edit" autoFocus rows={5} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex gap-2"><Button type="submit" size="sm" disabled={busy || !text.trim()}>Salva modifica</Button><Button size="sm" variant="ghost" onClick={() => onEditing(false)}>Annulla</Button></div>
    </form> : paragraph ? <div className="flex flex-wrap gap-2 max-md:[&_button]:h-12">
      <Button size="sm" disabled={busy} onClick={() => onDecide('accepted')}><Check />Accetta</Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => onEditing(true)}><Pencil />Modifica</Button>
    </div> : <div ref={controls} className="flex gap-2 max-md:[&_button]:h-12 max-md:[&_button]:min-w-12">
      {(!suggestion || editing) && <IconButton label={suggestion || editing && modified ? 'Applica la tua correzione' : 'Accetta la correzione'} icon={Check} variant="solid" disabled={busy || (editing && modified && !text.trim())} onClick={() => editing ? apply() : onDecide('accepted')} />}
      <IconButton label="Mantieni il testo attuale" icon={X} className="border" disabled={busy} onClick={() => { cancelEdit(); onDecide('rejected') }} />
    </div>}

  </Card>
}
