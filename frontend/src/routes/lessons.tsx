import { Brain, Download, Images, PanelRightClose, PanelRightOpen, Pencil, Plus } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { useDismissNotice, type Notice } from '@/api/documentEdit'
import { useLesson, useLessonDocument, useLessons } from '@/api/hooks'
import { useSettings } from '@/api/settings'
import { AudioPlayer } from '@/components/lesson/AudioPlayer'
import { AudioProvider } from '@/components/lesson/audio'
import { CostPanel } from '@/components/lesson/CostPanel'
import { DocumentEditNotice } from '@/components/lesson/DocumentEditNotice'
import type { DocumentSaveResult } from '@/components/lesson/DocumentEditor'
import { DocumentView } from '@/components/lesson/DocumentView'
import { JobsPanel } from '@/components/lesson/JobsPanel'
import { PhasePanel } from '@/components/lesson/PhasePanel'
import { PhaseBadges } from '@/components/PhaseBadges'
import { LessonJobBanner } from '@/components/jobs/JobsIndicator'
import { PhaseProgress } from '@/components/jobs/PhaseProgress'
import { LessonsHeaderActions, LessonsList, SelectionBar } from '@/components/lessons/LessonsView'
import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { useOpenNewLesson } from '@/components/shell/newLesson'
import { useJob, useJobs } from '@/api/jobs'
import { isActive } from '@/lib/jobs'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { lessonsGroups, shortDate, subjectName, useLessonsPrefs } from '@/lib/lessonsPage'
import { cn } from '@/lib/utils'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { STATE_LABELS, formatCost, lessonTitle } from '@/lib/format'

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

const SIDE_PANEL_KEY = 'rt-lesson-side-panel'

/** Pannello laterale della lezione (fasi, job, costi): aperto di default, si può nascondere
 * per leggere il documento a tutta larghezza. La scelta resta nel browser. */
function useSidePanel(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(SIDE_PANEL_KEY) !== 'closed'
    } catch {
      return true
    }
  })
  const update = (next: boolean) => {
    setOpen(next)
    try {
      localStorage.setItem(SIDE_PANEL_KEY, next ? 'open' : 'closed')
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }
  return [open, update]
}

export function LessonPage() {
  const id = Number(useParams().lessonId)
  const [editingDocument, setEditingDocument] = useState(false)
  const [panelOpen, setPanelOpen] = useSidePanel()
  const lesson = useLesson(id)
  const document = useLessonDocument(id)
  const back = { to: '/', label: 'Lezioni' }
  if (lesson.isPending || lesson.isError) {
    return (
      <>
        <PageHeader title="Lezione" muted titleAs="p" back={back} />
        <PageBody>
          {lesson.isPending ? <DocumentSkeleton /> : <Alert tone="danger">{errorMessage(lesson.error)}</Alert>}
        </PageBody>
      </>
    )
  }
  const l = lesson.data
  const sections = document.data?.sections ?? []
  const path = [l.materia ? subjectName(l.materia) : null, l.docente?.trim() || null, l.data ? shortDate(l.data) : null].filter(Boolean).join(' · ')
  return (
    <AudioProvider>
      <PageHeader title={path || lessonTitle(l)} muted titleAs="p" back={back} />
      <PageBody>
      <section className="flex flex-col gap-4">
        <Card className="p-5">
          {/* Azioni sempre sotto il titolo: accanto finivano a destra o sotto a seconda di
              quanto era lungo il titolo. */}
          <h1 className="text-xl font-bold tracking-tight">{lessonTitle(l)}</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {[l.materia, l.data, l.argomenti, l.state ? STATE_LABELS[l.state] ?? l.state : null].filter(Boolean).join(' · ')}
          </p>
          <div className="mt-3">
            <LessonActions lessonId={id} actions={l.actions} />
          </div>
          <div className="mt-3">
            <PhaseBadges phases={l.phases} />
          </div>
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t pt-3 text-xs">
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Segmenti</dt>
              <dd>{l.segment_count}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Issue da valutare</dt>
              <dd>
                {l.pending_issues}
                {l.phases.review && l.phases.review !== 'MISSING' && (
                  <Link to={`/lezioni/${id}/revisione`} className="ml-2 font-semibold text-link hover:underline">
                    {l.pending_issues > 0 ? 'Rivedi →' : 'Vedi la revisione'}
                  </Link>
                )}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Costo</dt>
              <dd className="tabular-nums">{formatCost(l.cost_usd)}</dd>
            </div>
          </dl>
          {l.error && <p className="mt-2 text-xs text-danger">{l.error}</p>}
        </Card>
        <LessonProgress lessonId={l.id} />
        <LessonJobBanner
          lessonId={l.id}
          review={Boolean(l.phases.review && l.phases.review !== 'MISSING')}
          extra={
            <button type="button" className="ml-auto inline-flex items-center gap-1 underline" aria-expanded={panelOpen}
              aria-controls="lesson-side-panel" onClick={() => setPanelOpen(!panelOpen)}>
              {panelOpen ? <PanelRightClose className="size-3.5" aria-hidden /> : <PanelRightOpen className="size-3.5" aria-hidden />}
              {panelOpen ? 'Nascondi fasi e costi' : 'Mostra fasi e costi'}
            </button>
          }
        />

        <div className={panelOpen ? 'grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]' : 'grid grid-cols-1 gap-4'}>
          <div className="flex min-w-0 flex-col gap-4">
            {l.has_audio && <AudioPlayer lessonId={id} sections={sections} />}
            <DocumentCard lesson={l} onEditingChange={setEditingDocument} />
          </div>
          <aside id="lesson-side-panel" className="flex flex-col gap-4" hidden={!panelOpen} aria-label="Fasi, job e costi">
            {panelOpen && (
              <>
                <PhasePanel lessonId={id} units={sections} editingDocument={editingDocument} />
                <JobsPanel lessonId={id} />
                <CostPanel lesson={l} />
              </>
            )}
          </aside>
        </div>
      </section>
      </PageBody>
    </AudioProvider>
  )
}

/** Pipeline o fase in corso sulla lezione: le due barre con gli eventi dal vivo (schermata 03). */
function LessonProgress({ lessonId }: { lessonId: number }) {
  const jobs = useJobs({ lesson_id: lessonId, limit: 20 })
  // Anche fermo su una decisione: l'avanzamento dice quale e porta a prenderla.
  const running = (jobs.data ?? []).find((j) => isActive(j.state) || j.state === 'waiting_for_decision')
  return running ? <PhaseProgress jobId={running.id} /> : null
}

// L'editor (CodeMirror) si carica solo quando si entra in modifica.
const DocumentEditor = lazy(() => import('@/components/lesson/DocumentEditor').then((m) => ({ default: m.DocumentEditor })))

const LEASE_RENEW_MS = 4 * 60 * 1000

/** Riquadro del documento: anteprima o documento finale, con la modifica dell'anteprima (beta). */
function DocumentCard({ lesson: l, onEditingChange }: { lesson: Schemas['LessonDetail']; onEditingChange: (editing: boolean) => void }) {
  const id = l.id
  const document = useLessonDocument(id)
  const settings = useSettings()
  const dismissNotice = useDismissNotice()
  const [mode, setMode] = useState<'view' | 'notice' | 'edit'>('view')
  const [leaseToken, setLeaseToken] = useState<string | null>(null)
  const [leaseError, setLeaseError] = useState<string | null>(null)
  useEffect(() => {
    if (!leaseToken) return
    // Il server fa scadere una sessione non rinnovata (scheda chiusa, crash): qui la teniamo viva.
    const renew = window.setInterval(() => {
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: id }, query: { token: leaseToken } } }))
        .catch((error: unknown) => setLeaseError(errorMessage(error)))
    }, LEASE_RENEW_MS)
    return () => {
      window.clearInterval(renew)
      void api.DELETE('/api/v1/lessons/{lesson_id}/document/lease', {
        params: { path: { lesson_id: id }, query: { token: leaseToken } },
      })
    }
  }, [leaseToken, id])
  const [saved, setSaved] = useState<DocumentSaveResult | null>(null)
  const dismissed = settings.data?.notices.dismissed ?? []
  const notices = ([...(l.pending_issues > 0 ? ['preview_edit_issues'] : []), 'preview_edit_beta'] as Notice[]).filter((n) => !dismissed.includes(n))

  const startEdit = () => {
    setSaved(null)
    if (notices.length > 0) setMode('notice')
    else void beginEdit()
  }
  const beginEdit = async (recover = false) => {
    try {
      const lease = await unwrap(api.POST('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: id }, query: { recover } } }))
      setLeaseToken(lease.token)
      setLeaseError(null)
      setMode('edit')
      onEditingChange(true)
    } catch (error) { setLeaseError(errorMessage(error)) }
  }
  return (
    <Card className="px-6 py-5">
      {document.isPending && <p className="text-sm text-muted-foreground">Carico il documento…</p>}
      {document.isError && <Alert tone="danger">{errorMessage(document.error)}</Alert>}
      {leaseError && <Alert tone="danger">{leaseError}<Button size="sm" variant="outline" className="ml-2" onClick={() => void beginEdit(true)}>Recupera sessione</Button></Alert>}
      {document.data && mode === 'edit' && (
        <Suspense fallback={<p className="text-sm text-muted-foreground">Preparo l'editor…</p>}>
          <DocumentEditor
          lessonId={id}
          markdown={document.data.markdown}
          leaseToken={leaseToken ?? undefined}
          onClose={(result) => {
            const finishClose = () => {
              setMode('view')
              onEditingChange(false)
              setLeaseToken(null)
              if (result?.changed) setSaved(result)
            }
            if (leaseToken) {
              void api.DELETE('/api/v1/lessons/{lesson_id}/document/lease', {
                params: { path: { lesson_id: id }, query: { token: leaseToken } },
              }).finally(finishClose)
            } else finishClose()
          }}
          />
        </Suspense>
      )}
      {document.data && mode !== 'edit' && (
        <>
          <div className="sticky top-3 z-10 flex h-0 justify-end">
            <Button
              variant="ghost"
              size="sm"
              className="-mr-3 -mt-2 size-8 bg-card p-0 opacity-20 hover:opacity-100 focus-visible:opacity-100"
              aria-label="Modifica l'anteprima"
              title="Modifica l'anteprima (beta)"
              onClick={startEdit}
            >
              <Pencil aria-hidden />
            </Button>
          </div>
          {saved && (
            <Alert tone="warning" className="mb-4" data-testid="document-edit-saved">
              Modifiche salvate nella bozza. Il documento finale va ricreato con la fase Documento.
              {saved.orphan_issues.length > 0 &&
                ` ${saved.orphan_issues.length === 1 ? "Un'issue è" : `${saved.orphan_issues.length} issue sono`} ora orfane: il testo a cui si riferivano non c'è più.`}
            </Alert>
          )}
          {!document.data.final && !saved && (
            <Alert className="mb-4">
              Anteprima dalla bozza: è quello che diventerà il documento finale quando esegui la fase Documento.
            </Alert>
          )}
          <DocumentView document={document.data} hasAudio={l.has_audio} lessonId={id} />
        </>
      )}
      {mode === 'notice' && (
        <DocumentEditNotice
          notices={notices}
          onCancel={() => setMode('view')}
          onConfirm={(dismiss) => {
            for (const n of dismiss) dismissNotice.mutate(n)
            void beginEdit()
          }}
        />
      )}
    </Card>
  )
}

const linkButton =
  'inline-flex h-8 items-center gap-2 rounded-md border border-input bg-card px-3 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring'

type ActionState = Schemas['LessonAction']
const NOT_LOADED: ActionState = { available: false, reason: 'Stato della lezione non disponibile.', preview: false }
const PREVIEW_HINT = 'Anteprima dalla bozza: il documento finale non è ancora stato creato o non è aggiornato.'

/** Un'azione dell'intestazione: sempre nello stesso posto; se non è disponibile resta
 * visibile, disabilitata, con il motivo nel tooltip (e per i lettori di schermo). */
function ActionSlot({ action, label, icon, children }: { action: ActionState; label: string; icon: ReactNode; children: (content: ReactNode, title?: string) => ReactNode }) {
  const reasonId = useId()
  const content = (
    <>
      {icon} {label}
    </>
  )
  if (action.available) return children(content, action.preview ? PREVIEW_HINT : undefined)
  return (
    <span title={action.reason ?? undefined} className="inline-flex" data-action-disabled={label}>
      <button type="button" disabled aria-describedby={reasonId} className={`${linkButton} cursor-not-allowed opacity-50`}>
        {content}
      </button>
      <span id={reasonId} className="sr-only">
        {action.reason}
      </span>
    </span>
  )
}

function LessonActions({ lessonId, actions }: { lessonId: number; actions?: Schemas['LessonActions'] | null }) {
  const a = actions ?? { recall: NOT_LOADED, images: NOT_LOADED, export_markdown: NOT_LOADED, export_zip: NOT_LOADED }
  return (
    <div className="flex flex-wrap gap-2" data-testid="lesson-actions">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Studio">
        <ActionSlot action={a.recall} label="Recall" icon={<Brain className="size-4" aria-hidden />}>
          {(content) => (
            <Link className={linkButton} to={`/lezioni/${lessonId}/recall`}>
              {content}
            </Link>
          )}
        </ActionSlot>
        <ActionSlot action={a.images} label="Arricchimento" icon={<Images className="size-4" aria-hidden />}>
          {(content) => (
            <Link className={linkButton} to={`/lezioni/${lessonId}/arricchimento`}>
              {content}
            </Link>
          )}
        </ActionSlot>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Scarica">
        <ActionSlot action={a.export_markdown} label="Markdown" icon={<Download className="size-4" aria-hidden />}>
          {(content, title) => (
            <a className={linkButton} href={`/api/v1/lessons/${lessonId}/export?format=markdown`} download title={title}>
              {content}
            </a>
          )}
        </ActionSlot>
        <ActionSlot action={a.export_zip} label="Tutti i dati (zip)" icon={<Download className="size-4" aria-hidden />}>
          {(content, title) => (
            <a className={linkButton} href={`/api/v1/lessons/${lessonId}/export?format=zip&scope=all`} download title={title}>
              {content}
            </a>
          )}
        </ActionSlot>
      </div>
    </div>
  )
}
