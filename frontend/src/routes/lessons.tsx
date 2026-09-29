import { Brain, Download, Images, LayoutDashboard, Pencil, Trash2 } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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
import { LessonFilters } from '@/components/LessonFilters'
import { useFilteredLessons } from '@/lib/lessonFilters'
import { optionRevealClass, useOptionKey } from '@/lib/optionKey'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { STATE_LABELS, formatCost, lessonTitle, type Lesson } from '@/lib/format'
import type { Area } from './types'
import { RelevancePage } from './relevance'

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <Card className="flex items-baseline gap-2.5 px-4 py-2.5">
      <strong className="text-2xl font-bold tabular-nums">{value}</strong>
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
    </Card>
  )
}

function LessonCard({ lesson }: { lesson: Lesson }) {
  const optionDown = useOptionKey()
  const [confirm, setConfirm] = useState(false)
  const [typed, setTyped] = useState('')
  const client = useQueryClient()
  const deletion = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: lesson.id } } })),
    onSuccess: () => { setConfirm(false); client.invalidateQueries({ queryKey: ['lessons'] }) },
  })
  const meta = [lesson.materia, lesson.data, lesson.state ? STATE_LABELS[lesson.state] ?? lesson.state : null].filter(Boolean)
  return (
    <Card className="group relative p-5" data-testid="lesson-card" data-lesson-id={lesson.id}>
      <Button type="button" variant="ghost" size="icon" aria-label={`Elimina ${lessonTitle(lesson)}`}
        className={`${optionRevealClass(optionDown)} absolute right-3 top-3 text-danger`}
        onClick={() => { setTyped(''); setConfirm(true) }}><Trash2 /></Button>
      <ConfirmDialog open={confirm} title="Elimina lezione" confirmLabel="Elimina"
        confirmDisabled={typed !== 'confermo' || deletion.isPending}
        onCancel={() => setConfirm(false)} onConfirm={() => deletion.mutate()}>
        <p>Eliminare definitivamente «{lessonTitle(lesson)}» e tutti i suoi file?</p>
        <label className="mt-3 block text-xs" htmlFor={`confirm-delete-${lesson.id}`}>Scrivi confermo</label>
        <input id={`confirm-delete-${lesson.id}`} className="mt-1 w-full rounded border p-2" value={typed} onChange={(event) => setTyped(event.target.value)} />
        {deletion.isError && <Alert tone="danger">{errorMessage(deletion.error)}</Alert>}
      </ConfirmDialog>
      <h2 className="pr-10 text-lg font-bold leading-snug tracking-tight">
        <Link to={`/lezioni/${lesson.id}`} className="hover:underline">
          {lessonTitle(lesson)}
        </Link>
      </h2>
      <p className="mb-3 mt-1 text-xs text-muted-foreground">{meta.join(' · ')}</p>
      <PhaseBadges phases={lesson.phases} />
      <div className="mt-4 flex flex-wrap items-baseline gap-3 border-t pt-3 text-xs">
        <span className="tabular-nums text-muted-foreground" title="Costo stimato">
          {formatCost(lesson.cost_usd)}
        </span>
        {lesson.pending_issues > 0 ? (
          <Link to={`/lezioni/${lesson.id}/revisione`} className="font-bold text-accent-foreground hover:underline">
            {lesson.pending_issues} issue da valutare →
          </Link>
        ) : (
          <span className="text-muted-foreground">Nessuna issue da valutare</span>
        )}
      </div>
      {lesson.error && <p className="mt-2 text-xs text-danger">{lesson.error}</p>}
    </Card>
  )
}

export function DashboardPage() {
  // Elenco completo una volta sola; testo, materia e stato si filtrano qui, senza una
  // richiesta per tasto (GET /lessons ricalcola fasi, issue e costi di ogni lezione).
  const all = useLessons()
  const lessons = all.data ?? []
  const { filters, setFilter, filtered } = useFilteredLessons(all.data)
  return (
    <section className="flex flex-col gap-5">
      <h1 className="sr-only">Dashboard</h1>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Stat value={lessons.length} label="Lezioni" />
        <Stat value={lessons.filter((l) => l.pending_issues > 0).length} label="Da rivedere" />
        <Stat value={lessons.filter((l) => l.state === 'completato').length} label="Completate" />
      </div>

      <LessonFilters lessons={lessons} filters={filters} onChange={setFilter} />

      {all.isError && <Alert tone="danger">{errorMessage(all.error)}</Alert>}
      {all.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {all.data && filtered.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {lessons.length === 0 ? 'Nessuna lezione nella cartella delle lezioni.' : 'Nessuna lezione corrisponde ai filtri.'}
        </Card>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {filtered.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
      </div>
    </section>
  )
}

export function LessonPage() {
  const id = Number(useParams().lessonId)
  const [editingDocument, setEditingDocument] = useState(false)
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
        <LessonJobBanner lessonId={l.id} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="flex min-w-0 flex-col gap-4">
            {l.has_audio && <AudioPlayer lessonId={id} sections={sections} />}
            <DocumentCard lesson={l} onEditingChange={setEditingDocument} />
          </div>
          <aside className="flex flex-col gap-4">
            <PhasePanel lessonId={id} units={sections} editingDocument={editingDocument} />
            <JobsPanel lessonId={id} />
            <CostPanel lesson={l} />
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
