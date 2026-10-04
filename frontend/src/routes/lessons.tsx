import { BookOpen, Brain, Download, Image, Info, Plus, ShieldCheck } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState, type RefObject } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useLesson, useLessonDocument, useLessons } from '@/api/hooks'
import { AudioPlayer } from '@/components/lesson/AudioPlayer'
import { AudioProvider } from '@/components/lesson/audio'
import { LessonPanel } from '@/components/lesson/LessonPanel'
import type { LessonEditorActions } from '@/components/lesson/LessonEditor'
import { LessonOutline } from '@/components/lesson/LessonOutline'
import { isRewriting, liveRewrite } from '@/components/lesson/lessonWorkflow'
import { isPanelView, OPEN_QUESTIONS_EVENT, PANEL_ID, usePanelView, type PanelView } from '@/lib/lessonPanel'
import { PhaseProgress } from '@/components/jobs/PhaseProgress'
import { LessonWaiting } from '@/components/jobs/JobsIndicator'
import { LessonsHeaderActions, LessonsList, SelectionBar } from '@/components/lessons/LessonsView'
import { PageHeader } from '@/components/shell/PageHeader'
import { useOpenNewLesson } from '@/components/shell/newLesson'
import { useJob, useJobs, useOutline } from '@/api/jobs'
import { isActive } from '@/lib/jobs'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { formatDuration, lessonsGroups, shortDate, subjectName, useLessonsPrefs } from '@/lib/lessonsPage'
import { cn } from '@/lib/utils'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { lessonTitle } from '@/lib/format'

export function DashboardPage() {
  // Elenco completo una volta sola; il testo si filtra qui, senza una richiesta per tasto
  // (GET /lessons ricalcola fasi, issue e costi di ogni lezione). Il testo cercato e la
  // materia (link vecchi con ?materia=) restano filtri dell'URL.
  const all = useLessons()
  const jobs = useJobs({ limit: 50 })
  const openNewLesson = useOpenNewLesson()
  const { filters, setFilter, resetFilters, filtered } = useFilteredLessons(all.data)
  const [prefs, setPrefs] = useLessonsPrefs()
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(() => new Set())
  const running = new Set((jobs.data ?? []).filter((j) => isActive(j.state) && j.lesson_id != null).map((j) => j.lesson_id!))
  const groups = lessonsGroups(filtered, prefs)
  const chosen = filtered.filter((l) => selected.has(l.id))
  useSearchShortcut('lessons-search')
  const stopSelecting = () => {
    setSelecting(false)
    setSelected(new Set())
  }
  return (
    <>
      <PageHeader
        title="Lezioni"
        actions={
          <LessonsHeaderActions
            prefs={prefs}
            onPrefs={setPrefs}
            query={filters.q}
            onQuery={(q) => setFilter('q', q)}
            selecting={selecting}
            onSelecting={(on) => (on ? setSelecting(true) : stopSelecting())}
          />
        }
      />
      <div className={cn('flex-1 px-7 py-6 max-md:px-4 max-md:py-2', selecting && 'pb-24')} data-testid="lessons-page">
        {all.isPending && <LessonsSkeleton />}
        {all.isError && (
          <p role="alert" className="flex items-center gap-3 text-body">
            <span className="text-danger">{errorMessage(all.error)}</span>
            <Button variant="outline" size="sm" onClick={() => void all.refetch()}>Riprova</Button>
          </p>
        )}
        {all.data?.length === 0 && (
          <p className="flex flex-wrap items-center gap-3 text-body text-muted-foreground" data-testid="lessons-empty">
            Nessuna lezione.
            <Button onClick={openNewLesson}><Plus aria-hidden />Nuova lezione</Button>
          </p>
        )}
        {all.data && all.data.length > 0 && filtered.length === 0 && (
          <p className="flex flex-wrap items-center gap-3 text-body text-muted-foreground" data-testid="lessons-empty">
            Nessuna lezione corrisponde alla ricerca.
            <Button variant="outline" size="sm" onClick={resetFilters}>Azzera</Button>
          </p>
        )}
        {filters.materia && filtered.length > 0 && (
          <p className="mb-4 text-meta text-muted-foreground">
            Solo {subjectName(filters.materia)}.{' '}
            <button type="button" className="underline" onClick={resetFilters}>Mostra tutte</button>
          </p>
        )}
        {filtered.length > 0 && (
          <LessonsList groups={groups} grouping={prefs.group} running={running} selecting={selecting} selected={selected} onSelected={setSelected} />
        )}
      </div>
      {selecting && <SelectionBar lessons={chosen} onCancel={stopSelecting} onDeleted={() => setSelected(new Set())} />}
    </>
  )
}

/** Caricamento: righe grigie della forma dell'elenco, non uno spinner. */
function LessonsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Carico le lezioni" role="status">
      <div className="mb-4 h-2.5 w-48 rounded-md bg-muted" />
      {[72, 56, 64, 48].map((width) => (
        <div key={width} className="flex min-h-14 items-center gap-3 px-2.5">
          <span className="size-1.5 rounded-full bg-muted" />
          <span className="h-2.5 rounded-md bg-muted" style={{ width: `${width}%` }} />
        </div>
      ))}
    </div>
  )
}

/** Dopo Avvia nel popup Nuova lezione: avanzamento finché il setup non ha creato la lezione,
 * poi la pagina della lezione (dove l'avanzamento continua). */
export function NewLessonPage() {
  const jobId = useParams().jobId ?? ''
  const job = useJob(jobId)
  const navigate = useNavigate()
  const lessonId = job.data?.lesson_id
  useEffect(() => {
    if (lessonId != null) navigate(`/lezioni/${lessonId}`, { replace: true })
  }, [lessonId, navigate])
  const options = ((job.data?.payload as Record<string, unknown> | undefined)?.options ?? {}) as Record<string, unknown>
  const path = [options.materia ? subjectName(String(options.materia)) : null, options.docente ? String(options.docente) : null, options.date ? shortDate(String(options.date)) : null]
    .filter(Boolean)
    .join(' · ')
  return (
    <>
      <PageHeader title={path || 'Nuova lezione'} muted titleAs="p" back={{ to: '/', label: 'Lezioni' }} />
      <article className="mx-auto w-full max-w-(--reading-width) px-4 pb-28 pt-7">
        <h1 className="mb-2 text-heading font-semibold leading-tight">Nuova lezione</h1>
        {job.isError && <Alert tone="danger">{errorMessage(job.error)}</Alert>}
        <PhaseProgress jobId={jobId} className="my-6" onRetried={(id) => navigate(`/lezioni/nuova/${id}`, { replace: true })} />
        <DocumentSkeleton />
      </article>
    </>
  )
}

/** Il testo che ancora manca (linee guida §4, "In corso"). */
function DocumentSkeleton() {
  return (
    <div aria-hidden>
      {[['40%', 14, 0], ['100%', 10, 0], ['92%', 10, 0], ['75%', 10, 0], ['35%', 14, 22], ['100%', 10, 0], ['88%', 10, 0]].map(([width, height, top], index) => (
        <div key={index} className="my-3 rounded-md bg-muted" style={{ width: String(width), height: Number(height), marginTop: Number(top) || undefined }} />
      ))}
    </div>
  )
}

/** "/" porta nel campo di ricerca (se non si sta già scrivendo altrove). */
function useSearchShortcut(inputId: string) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      const input = document.getElementById(inputId)
      if (!input) return
      event.preventDefault()
      input.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [inputId])
}

export function LessonPage() {
  const id = Number(useParams().lessonId)
  const editorActions = useRef<LessonEditorActions | null>(null)
  const [editingDocument, setEditingDocument] = useState(false)
  const [storedPanel, storePanel] = usePanelView()
  const [params, setParams] = useSearchParams()
  // ?panel=… (link da altre pagine e redirect delle pagine tolte) apre quel pannello
  const requestedPanel = params.get('panel')
  const panel = isPanelView(requestedPanel) ? requestedPanel : storedPanel
  // Domande su una parte: unità (dal link ?unita= o dal menu contestuale) e testo selezionato
  const [selectionContext, setSelectionContext] = useState<{ units: string[]; text: string } | null>(() => {
    const units = params.get('unita')?.split(',').filter(Boolean)
    return units?.length ? { units, text: '' } : null
  })
  const setPanel = (next: PanelView | null) => {
    storePanel(next)
    if (next !== 'domande') setSelectionContext(null)
    if (params.has('panel') || params.has('issue') || params.has('unita')) {
      const query = new URLSearchParams(params)
      query.delete('panel')
      query.delete('issue')
      query.delete('unita')
      setParams(query, { replace: true })
    }
  }
  const openQuestions = useRef(setPanel)
  useEffect(() => { openQuestions.current = setPanel })
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ units: string[]; text: string }>).detail
      if (!detail) return
      setSelectionContext(detail)
      openQuestions.current('domande')
    }
    window.addEventListener(OPEN_QUESTIONS_EVENT, handler)
    return () => window.removeEventListener(OPEN_QUESTIONS_EVENT, handler)
  }, [])
  const [editorText, setEditorText] = useState<{ id: number; markdown: string } | null>(null)
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  const outline = useOutline(id)
  const jobs = useJobs({ lesson_id: id, limit: 20 })
  const job = jobs.data?.find((j) => isActive(j.state)) ?? jobs.data?.find((j) => j.state === 'waiting_for_decision')
  const back = { to: '/', label: 'Lezioni' }
  if (lesson.isPending || lesson.isError) {
    return (
      <>
        <PageHeader title="Lezione" muted titleAs="p" back={back} />
        <article className="mx-auto w-full max-w-(--reading-width) px-4 pb-28 pt-7">
          {lesson.isPending ? <DocumentSkeleton /> : <Alert tone="danger">{errorMessage(lesson.error)}</Alert>}
        </article>
      </>
    )
  }
  const l = lesson.data
  // Le lezioni già rielaborate (anche importate da versioni precedenti) non richiedono il gate della scaletta.
  const pendingOutline = !!outline.data && !outline.data.approved && l.phases.rewrite !== 'VALID'
  const sections = document.data?.sections ?? []
  const path = [l.materia ? subjectName(l.materia) : null, l.data ? shortDate(l.data) : null, l.docente?.trim() || null].filter(Boolean).join(' · ')
  const meta = [l.unit_count != null ? `${l.unit_count} unità` : null, l.duration_seconds ? formatDuration(l.duration_seconds) : null].filter(Boolean).join(' · ')
  const toggle = (view: PanelView) => setPanel(panel === view ? null : view)
  return (
    <AudioProvider>
      <PageHeader
        title={null}
        muted
        titleAs="p"
        back={back}
        actions={<LessonHeaderActions lesson={l} panel={panel} onToggle={toggle} />}
      />
      <div className={cn('flex-1 px-7 max-md:px-4', panel && 'xl:pr-[calc(24rem+28px)]')}>
        <article className="mx-auto w-full max-w-(--reading-width) pb-28 pt-7 max-md:pt-3" data-testid="lesson-page">
          <h1 className="mb-2 text-heading font-semibold leading-tight">{lessonTitle(l)}</h1>
          {path && <p className="text-meta text-muted-foreground" data-testid="lesson-path">{path}</p>}
          {meta && <p className="text-meta text-muted-foreground" data-testid="lesson-meta">{meta}</p>}
          <LessonProgress lessonId={l.id} job={job} pendingOutline={pendingOutline} />
          {outline.isError && !(outline.error instanceof ApiError && outline.error.code === 'outline_not_found') && <Alert tone="danger" className="mt-5">{errorMessage(outline.error)}<Button size="sm" variant="outline" onClick={() => void outline.refetch()}>Riprova</Button></Alert>}
          {outline.data && pendingOutline
            ? <LessonOutline key={outline.data.expires_at ?? JSON.stringify(outline.data.macro_sections)} lessonId={id} outline={outline.data} busy={!!job && isActive(job.state)} mock={job?.payload.mock === true || (typeof job?.payload.options === 'object' && job.payload.options != null && 'mock' in job.payload.options && job.payload.options.mock === true)} refresh={outline.refetch} />
            : <DocumentCard lesson={l} outline={outline.data} job={job} actionsRef={editorActions} reviewOpen={panel === 'verifica'} classifierOpen={panel === 'classificatore'} onDocumentChange={(markdown) => setEditorText({ id, markdown })} onEditingChange={setEditingDocument} />}
        </article>
      </div>
      {l.has_audio && <AudioPlayer lessonId={id} />}
      {panel && (
        <LessonPanel
          view={panel}
          lesson={l}
          sections={sections}
          editingDocument={editingDocument}
          reviewMarkdown={editorText?.id === id ? editorText.markdown : document.data?.markdown}
          beforeReviewAction={async () => { await editorActions.current?.flush() }}
          onClose={() => setPanel(null)}
          onSwitchView={(next) => setPanel(next)}
          selectionContext={selectionContext}
          onClearSelection={() => setSelectionContext(null)}
        />
      )}
    </AudioProvider>
  )
}

/** Azioni della lezione nell’ordine del wireframe Main. */
function LessonHeaderActions({ lesson: l, panel, onToggle }: { lesson: Schemas['LessonDetail']; panel: PanelView | null; onToggle: (view: PanelView) => void }) {
  const a = l.actions ?? { recall: NOT_LOADED, images: NOT_LOADED, export_markdown: NOT_LOADED, export_zip: NOT_LOADED }
  const reason = (action: ActionState) => (action.available ? null : (action.reason ?? 'non disponibile'))
  return (
    <div className="flex items-center gap-0.5" data-testid="lesson-actions">
      <IconButton label="Domande" icon={Brain} active={panel === 'domande'} aria-expanded={panel === 'domande'} aria-controls={PANEL_ID} onClick={() => onToggle('domande')} />
      <IconLink label="Studio" icon={BookOpen} to={`/studio/lezione/${l.id}`} unavailable={reason(a.recall)} />
      <IconButton label="Arricchimento" icon={Image} active={panel === 'arricchimento'} aria-expanded={panel === 'arricchimento'} aria-controls={PANEL_ID} onClick={() => onToggle('arricchimento')} />
      <IconButton label="Verifica con LLM" icon={ShieldCheck} active={panel === 'verifica'} aria-expanded={panel === 'verifica'} aria-controls={PANEL_ID} onClick={() => onToggle('verifica')} />
      <IconButton label="Dettagli" icon={Info} active={panel === 'dettagli'} aria-expanded={panel === 'dettagli'} aria-controls={PANEL_ID} onClick={() => onToggle('dettagli')} />
      <LinkMenuButton
        label="Esporta"
        icon={Download}
        items={[
          { label: 'Markdown', href: `/api/v1/lessons/${l.id}/export?format=markdown`, download: true, title: a.export_markdown.preview ? PREVIEW_HINT : undefined, unavailable: reason(a.export_markdown) },
          { label: 'Tutti i dati (zip)', href: `/api/v1/lessons/${l.id}/export?format=zip&scope=all`, download: true, title: a.export_zip.preview ? PREVIEW_HINT : undefined, unavailable: reason(a.export_zip) },
        ]}
      />
    </div>
  )
}

/** Pipeline o fase in corso sulla lezione: le due barre con gli eventi dal vivo (schermata 03). */
function LessonProgress({ lessonId, job, pendingOutline }: { lessonId: number; job?: Schemas['Job']; pendingOutline: boolean }) {
  return (
    <>
      {!pendingOutline && <LessonWaiting lessonId={lessonId} className="mt-5" />}
      {job && !(job.state === 'waiting_for_decision' && pendingOutline) ? <PhaseProgress jobId={job.id} className="my-6" /> : null}
    </>
  )
}

// L'editor (CodeMirror con atomic-editor) è un pezzo a sé: si carica con la pagina della lezione.
const LessonEditor = lazy(() => import('@/components/lesson/LessonEditor').then((m) => ({ default: m.LessonEditor })))

/** Documento della lezione: si legge e si modifica nello stesso posto, come in Obsidian. */
function DocumentCard({ lesson: l, outline, job, onEditingChange, actionsRef, reviewOpen, classifierOpen, onDocumentChange }: { outline?: Schemas['Outline']; job?: Schemas['Job']; classifierOpen: boolean; reviewOpen: boolean; onDocumentChange: (markdown: string) => void; actionsRef: RefObject<LessonEditorActions | null>; lesson: Schemas['LessonDetail']; onEditingChange: (editing: boolean) => void }) {
  const id = l.id
  const document = useLessonDocument(id)
  const running = !!job && isActive(job.state)
  const live = outline && job && isRewriting(job, l.phases.rewrite === 'VALID') ? liveRewrite(outline, document.data, job) : null
  const doc = live?.document ?? document.data
  return (
    <div className="mt-6">
      {document.isPending && !live && <DocumentSkeleton />}
      {/* In corso: lo scheletro al posto del testo che ancora manca (linee guida §4). */}
      {document.isError && !live && (running ? <DocumentSkeleton /> : <Alert tone="danger">{errorMessage(document.error)}</Alert>)}
      {doc && (
        <>
          {!doc.final && !live && (
            <p className="mb-2 text-meta text-muted-foreground" data-testid="document-preview-note">
              Bozza
            </p>
          )}
          <Suspense fallback={<DocumentSkeleton />}>
            <LessonEditor
              key={id}
              classifierOpen={classifierOpen}
              reviewOpen={reviewOpen}
              onDocumentChange={onDocumentChange}
              actionsRef={actionsRef}
              lessonId={id}
              document={doc}
              unitTasks={live?.tasks}
              hasAudio={l.has_audio}
              ready={l.phases.rewrite === 'VALID'}
              locked={running}
              onEditingChange={onEditingChange}
            />
          </Suspense>
        </>
      )}
    </div>
  )
}

type ActionState = Schemas['LessonAction']
const NOT_LOADED: ActionState = { available: false, reason: 'Stato della lezione non disponibile.', preview: false }
const PREVIEW_HINT = 'Anteprima dalla bozza: il documento finale non è ancora stato creato o non è aggiornato.'
