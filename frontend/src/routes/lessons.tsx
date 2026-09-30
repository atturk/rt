import { Brain, Download, Images, LayoutDashboard, PanelRightClose, PanelRightOpen, Pencil } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'

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
import { LessonList, LessonViewControls } from '@/components/LessonList'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { groupLessons, sortLessons, useLessonViewPrefs } from '@/lib/lessonView'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { STATE_LABELS, formatCost, lessonTitle } from '@/lib/format'
import type { Area } from './types'
import { RelevancePage } from './relevance'

export function DashboardPage() {
  // Elenco completo una volta sola; il testo si filtra qui, senza una richiesta per tasto
  // (GET /lessons ricalcola fasi, issue e costi di ogni lezione). Materia e stato restano
  // filtri dell'URL (link dalla barra laterale), azzerabili da "Azzera filtri".
  // La ricerca cerca già in materia, titolo, docente e data: niente riquadri né menu separati.
  const all = useLessons()
  const lessons = all.data ?? []
  const { filters, setFilter, resetFilters, filtered } = useFilteredLessons(all.data)
  const { prefs, update, sortBy, toggleGroup } = useLessonViewPrefs()
  const groups = groupLessons(sortLessons(filtered, prefs.sort, prefs.dir), prefs.group, prefs.sort === 'data' ? prefs.dir : 'desc')
  const hasFilters = Boolean(filters.q || filters.materia || filters.state)
  useSearchShortcut('filter-q')
  return (
    <section className="flex flex-col gap-5">
      <h1 className="sr-only">Dashboard</h1>

      {all.isError && <Alert tone="danger">{errorMessage(all.error)}</Alert>}
      {all.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {all.data && lessons.length > 0 && (
        <LessonViewControls shown={filtered.length} total={lessons.length} filtered={hasFilters}
          onReset={resetFilters} prefs={prefs} onChange={update}
          search={{ id: 'filter-q', value: filters.q, onChange: (value) => setFilter('q', value) }} />
      )}
      {all.data && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {lessons.length === 0 ? 'Nessuna lezione: importane una da un audio.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      {filtered.length > 0 && (
        <LessonList groups={groups} grouped={prefs.group !== 'nessuno'} prefs={prefs} onSort={sortBy} onToggleGroup={toggleGroup} />
      )}
    </section>
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
  if (lesson.isPending) return <p className="text-sm text-muted-foreground">Carico la lezione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  const l = lesson.data
  const sections = document.data?.sections ?? []
  return (
    <AudioProvider>
      <section className="flex flex-col gap-4">
        <Link to="/" className="text-xs text-muted-foreground hover:underline">
          ← Tutte le lezioni
        </Link>
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
                  <Link to={`/lezioni/${id}/revisione`} className="ml-2 font-semibold text-accent-foreground hover:underline">
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
    </AudioProvider>
  )
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
        <ActionSlot action={a.images} label="Immagini" icon={<Images className="size-4" aria-hidden />}>
          {(content) => (
            <Link className={linkButton} to={`/lezioni/${lessonId}/immagini`}>
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

export const lessonsArea: Area = {
  routes: [
    { index: true, element: <DashboardPage /> },
    { path: 'lezioni/:lessonId', element: <LessonPage /> },
    { path: 'lezioni/:lessonId/rilevanza', element: <RelevancePage /> },
  ],
  nav: [{ to: '/', label: 'Lezioni', icon: LayoutDashboard, end: true }],
}
