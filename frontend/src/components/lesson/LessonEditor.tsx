import { AtomicCodeMirrorEditor, type AtomicCodeMirrorEditorHandle } from '@atomic-editor/editor'
import '@atomic-editor/editor/styles.css'
import { EditorView } from '@codemirror/view'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject, type MouseEvent } from 'react'
import { useLocation } from 'react-router'

import { api, ApiError, CSRF_COOKIE, CSRF_HEADER, errorMessage, readCookie, unwrap, type Schemas } from '@/api/client'
import { lessonKeys } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { activeUnit } from '@/lib/audio'
import { markdownBlocks, partOfRange } from '@/lib/documentParts'
import { useLessonAudio } from './audio'
import { DocumentMenu, type PartLocator } from './DocumentMenu'
import { EnrichmentPortals } from './Enrichment'
import { lessonImages, lessonUnits, setSlots, unitRanges } from './lessonUnits'
import { SEEK_EVENT, timecodeLock } from './timecodeLock'

type Problem = Schemas['DocumentEditProblem']
type Status =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | { kind: 'saving' }
  | { kind: 'saved'; final: boolean }
  | { kind: 'invalid'; problems: Problem[] }
  | { kind: 'error'; message: string; busy: boolean }

const SAVE_DELAY_MS = 1200
// Il lease blocca i job della lezione: si prende alla prima modifica e si lascia dopo un po' di quiete.
const LEASE_IDLE_MS = 60 * 1000
const LEASE_RENEW_MS = 4 * 60 * 1000


function problemsOf(error: unknown): Problem[] | null {
  if (!(error instanceof ApiError) || error.code !== 'document_invalid') return null
  const errors = (error.details as { errors?: Problem[] } | undefined)?.errors
  return Array.isArray(errors) ? errors : null
}

function viewOf(handle: AtomicCodeMirrorEditorHandle | null): EditorView | null {
  const content = handle?.getContentDOM()
  return content ? EditorView.findFromDOM(content) : null
}

export type LessonEditorActions = { flush: () => Promise<void> }

type Props = {
  actionsRef?: RefObject<LessonEditorActions | null>
  lessonId: number
  document: Schemas['LessonDocument']
  hasAudio: boolean
  /** Rielaborazione pronta (per il menu contestuale). */
  ready: boolean
  /** Un job sta lavorando sulla lezione: si legge soltanto. */
  locked: boolean
  /** Si sta modificando (lease preso): le fasi aspettano. */
  onEditingChange?: (editing: boolean) => void
}

/**
 * Documento della lezione come in Obsidian (atomic-editor): si legge e si modifica nello stesso
 * posto, il Markdown si vede reso e i segni compaiono solo sulla riga del cursore. Le modifiche
 * si salvano da sole nella bozza dopo una breve pausa; i timecode sono bloccati (clic: ascolta,
 * triplo clic: modifica). Il documento finale va poi ricreato con la fase Documento.
 */
export function LessonEditor({ lessonId, document: doc, hasAudio, ready, locked, onEditingChange, actionsRef }: Props) {
  const handle = useRef<AtomicCodeMirrorEditorHandle | null>(null)
  const surface = useRef<HTMLDivElement>(null)
  const { currentTime, seek } = useLessonAudio()
  const current = hasAudio ? activeUnit(doc.sections, currentTime) : null
  const unitIds = useMemo(() => doc.sections.map((s) => s.unit_id), [doc.sections])
  const { hash } = useLocation()
  const extensions = useMemo(() => [
    timecodeLock,
    lessonUnits,
    lessonImages(lessonId),
    EditorView.contentAttributes.of({ 'aria-label': 'Documento della lezione', 'aria-multiline': 'true' }),
  ], [lessonId])

  // Il testo che l'editor mostra al montaggio; cambia (e l'editor riparte) solo se il documento
  // cambia sul server per altre vie (un job), non per i nostri salvataggi.
  const [source, setSource] = useState({ key: 0, markdown: doc.markdown })
  const [text, setText] = useState(doc.markdown)
  const saved = useRef(doc.markdown)
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [lease, setLease] = useState<string | null>(null)
  const client = useQueryClient()
  // Ultimo Markdown visto dal server, e se la prossima novità è l'eco di un nostro salvataggio.
  const server = useRef(doc.markdown)

  useEffect(() => {
    if (doc.markdown === server.current) return
    server.current = doc.markdown
    if (doc.markdown === saved.current) return
    // modifiche non ancora salvate: restano quelle dell'utente
    if (text !== saved.current) return
    saved.current = doc.markdown
    // oxlint-disable-next-line react/set-state-in-effect
    setText(doc.markdown)
    setSource((s) => ({ key: s.key + 1, markdown: doc.markdown }))
  }, [doc.markdown, text])

  const leaseRef = useRef<string | null>(null)
  const savingRef = useRef<Promise<void> | null>(null)
  const acquire = useCallback(async (recover = false) => {
    const result = await unwrap(api.POST('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: lessonId }, query: { recover } } }))
    leaseRef.current = result.token
    setLease(result.token)
    return result.token
  }, [lessonId])

  const persist = useCallback(async (markdown: string, recover = false) => {
    setStatus({ kind: 'saving' })
    try {
      const token = leaseRef.current ?? (await acquire(recover))
      const result = await unwrap(api.PUT('/api/v1/lessons/{lesson_id}/document/draft', {
        params: { path: { lesson_id: lessonId } }, body: { markdown, lease_token: token },
      }))
      saved.current = markdown
      setStatus({ kind: 'saved', final: doc.final && result.changed })
      // rilegge documento, fasi e build da rifare
      void client.invalidateQueries({ queryKey: lessonKeys.all(lessonId) })
      void client.invalidateQueries({ queryKey: ['lessons'] })
    } catch (error) {
      const problems = problemsOf(error)
      if (problems) setStatus({ kind: 'invalid', problems })
      else setStatus({ kind: 'error', message: errorMessage(error), busy: error instanceof ApiError && error.code === 'document_edit_busy' })
      throw error
    }
  }, [acquire, lessonId, doc.final, client])

  const save = useCallback(async (markdown: string, recover = false) => {
    if (savingRef.current) await savingRef.current.catch(() => undefined)
    if (markdown === saved.current) return
    const pending = persist(markdown, recover)
    savingRef.current = pending
    try { await pending } finally { if (savingRef.current === pending) savingRef.current = null }
  }, [persist])
  useEffect(() => {
    if (!actionsRef) return
    actionsRef.current = { flush: async () => {
      const markdown = viewOf(handle.current)?.state.doc.toString() ?? text
      await save(markdown)
      if (leaseRef.current) {
        await unwrap(api.DELETE('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: lessonId }, query: { token: leaseRef.current } } }))
        leaseRef.current = null
        setLease(null)
      }
    } }
    return () => { actionsRef.current = null }
  }, [actionsRef, text, save, lessonId])

  // Salvataggio dopo una pausa nella scrittura.
  useEffect(() => {
    if (text === saved.current || locked) return
    // oxlint-disable-next-line react/set-state-in-effect
    setStatus({ kind: 'pending' })
    const timer = window.setTimeout(() => void save(text).catch(() => undefined), SAVE_DELAY_MS)
    return () => window.clearTimeout(timer)
    // persist cambia con il lease: non deve far ripartire l'attesa
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, locked])

  // Lease: rinnovato mentre si scrive, lasciato dopo un po' di quiete o all'uscita.
  useEffect(() => {
    if (!lease) return
    const release = () => void api.DELETE('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: lessonId }, query: { token: lease } } })
    const renew = window.setInterval(() => {
      void api.POST('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: lessonId }, query: { token: lease } } })
    }, LEASE_RENEW_MS)
    const idle = window.setTimeout(() => {
      release()
      leaseRef.current = null
      setLease(null)
    }, LEASE_IDLE_MS)
    return () => {
      window.clearInterval(renew)
      window.clearTimeout(idle)
    }
  }, [lease, lessonId, text])
  useEffect(() => {
    if (!lease) return
    // Ricarica o chiusura della scheda: React non smonta, il lease resterebbe a bloccare i job
    // fino alla scadenza. keepalive porta a termine la richiesta anche a pagina chiusa.
    const onPageHide = () => {
      const csrf = readCookie(CSRF_COOKIE)
      void fetch(`/api/v1/lessons/${lessonId}/document/lease?token=${encodeURIComponent(lease)}`, {
        method: 'DELETE', credentials: 'same-origin', keepalive: true, headers: csrf ? { [CSRF_HEADER]: csrf } : {},
      })
    }
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      void api.DELETE('/api/v1/lessons/{lesson_id}/document/lease', { params: { path: { lesson_id: lessonId }, query: { token: lease } } })
    }
  }, [lease, lessonId])

  useEffect(() => {
    onEditingChange?.(lease != null)
  }, [lease, onEditingChange])

  // Uscita con modifiche non salvate: il browser chiede conferma.
  useEffect(() => {
    if (text === saved.current) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [text, status])

  // Riquadri dell'arricchimento in fondo alle unità.
  const slots = useMemo(() => Object.fromEntries(unitIds.map((id) => {
    const el = window.document.createElement('div')
    el.className = 'rt-enrichment-slot'
    el.dataset.unit = id
    return [id, el]
  })), [unitIds])
  useEffect(() => {
    viewOf(handle.current)?.dispatch({ effects: setSlots.of(slots) })
  }, [slots, source.key])

  // Clic su un timecode: l'audio parte da lì.
  useEffect(() => {
    const node = surface.current
    if (!node || !hasAudio) return
    const onSeek = (event: Event) => seek((event as CustomEvent<number>).detail)
    node.addEventListener(SEEK_EVENT, onSeek)
    return () => node.removeEventListener(SEEK_EVENT, onSeek)
  }, [seek, hasAudio])

  // "Vai all'unità" (#unit-<id>): l'unità in cima.
  useEffect(() => {
    const view = viewOf(handle.current)
    const unitId = hash.startsWith('#unit-') ? decodeURIComponent(hash.slice('#unit-'.length)) : ''
    const unit = view && unitId ? unitRanges(view.state).find((u) => u.id === unitId) : null
    if (view && unit) view.dispatch({ effects: EditorView.scrollIntoView(unit.from, { y: 'start', yMargin: 80 }) })
  }, [hash, source.key])

  // Il clic destro su una parola la seleziona (macOS): conta solo una selezione già fatta prima.
  const selectedBefore = useRef(false)
  const locate: PartLocator = useCallback((event: MouseEvent) => {
    const view = viewOf(handle.current)
    if (!view || !view.dom.contains(event.target as Node)) return null
    const { state } = view
    const sel = state.selection.main
    const lines = state.doc.toString().split('\n')
    const blocks = markdownBlocks(lines, unitIds)
    if (!sel.empty && selectedBefore.current) {
      const text = state.sliceDoc(sel.from, sel.to)
      if (!text.trim()) return null
      const rect = view.coordsAtPos(sel.from) ?? { left: event.clientX, bottom: event.clientY }
      const units = partOfRange(blocks, state.doc.lineAt(sel.from).number - 1, state.doc.lineAt(sel.to).number - 1, unitIds)
      return { text, units, anchor: { x: rect.left, y: rect.bottom } }
    }
    const pos = view.posAtCoords({ x: event.clientX, y: event.clientY })
    if (pos == null) return null
    const line = state.doc.lineAt(pos)
    if (!/^#{2,3}\s/.test(line.text)) return null
    const rect = view.coordsAtPos(line.from) ?? { left: event.clientX, bottom: event.clientY }
    return {
      text: line.text.replace(/^#+\s*/, ''),
      units: partOfRange(blocks, line.number - 1, line.number - 1, unitIds),
      anchor: { x: rect.left, y: rect.bottom },
    }
  }, [unitIds])

  // Torna all'ultimo testo salvato (l'editor riparte da lì).
  const restore = () => {
    setText(saved.current)
    setSource((s) => ({ key: s.key + 1, markdown: saved.current }))
    setStatus({ kind: 'idle' })
  }
  // Il Markdown com'è adesso, per continuare altrove; poi si ripristina.
  const downloadAndRestore = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
    const link = window.document.createElement('a')
    link.href = url
    link.download = `lezione-${lessonId}-modifiche.md`
    link.click()
    URL.revokeObjectURL(url)
    restore()
  }

  const goToLine = (lineNo: number) => {
    const view = viewOf(handle.current)
    if (!view) return
    const line = view.state.doc.line(Math.min(Math.max(lineNo, 1), view.state.doc.lines))
    view.dispatch({ selection: { anchor: line.from, head: line.to }, scrollIntoView: true })
    view.focus()
  }

  return (
    <>
      <EditorStatus
        status={status}
        locked={locked}
        onGoToLine={goToLine}
        onRecover={() => void save(text, true).catch(() => undefined)}
        onRestore={restore}
        onDownloadAndRestore={downloadAndRestore}
      />
      <DocumentMenu lessonId={lessonId} unitIds={unitIds} ready={ready} locate={locate}>
        <div
          ref={surface}
          className="rt-lesson-editor"
          data-testid="lesson-document"
          data-active-unit={current ?? ''}
          onMouseDownCapture={(e) => {
            if (e.button !== 2) return
            selectedBefore.current = !(viewOf(handle.current)?.state.selection.main.empty ?? true)
            // il clic destro non sposta il cursore: niente scorrimento che chiuderebbe il menu
            e.preventDefault()
            e.stopPropagation()
          }}
          onKeyDownCapture={(e) => {
            // Esc toglie il cursore: si torna a leggere.
            if (e.key === 'Escape') (window.document.activeElement as HTMLElement | null)?.blur()
          }}
        >
          <AtomicCodeMirrorEditor
            documentId={`lesson-${lessonId}-${source.key}`}
            markdownSource={source.markdown}
            onMarkdownChange={setText}
            editorHandleRef={handle}
            extensions={extensions}
            readOnly={locked}
            blurEditorOnMount
          />
        </div>
      </DocumentMenu>
      <EnrichmentPortals slots={slots} lessonId={lessonId} />
    </>
  )
}

/** Stato del salvataggio, discreto: in alto a destra sopra il testo. */
function EditorStatus({ status, locked, onGoToLine, onRecover, onRestore, onDownloadAndRestore }: {
  status: Status
  locked: boolean
  onGoToLine: (line: number) => void
  onRecover: () => void
  onRestore: () => void
  onDownloadAndRestore: () => void
}) {
  if (locked) {
    return <p className="mb-3 text-meta text-muted-foreground" data-testid="editor-status">Un job sta lavorando sulla lezione: la modifica riprende quando finisce.</p>
  }
  if (status.kind === 'invalid') {
    return <Incompatible problems={status.problems} onGoToLine={onGoToLine} onRestore={onRestore} onDownloadAndRestore={onDownloadAndRestore} />
  }
  if (status.kind === 'error') {
    return (
      <p className="mb-3 text-meta text-danger" role="alert" data-testid="editor-status">
        {status.message}
        {status.busy && <Button size="sm" variant="outline" className="ml-2" onClick={onRecover}>Modifica qui</Button>}
      </p>
    )
  }
  const label = {
    idle: '',
    pending: 'Modifiche non salvate…',
    saving: 'Salvo…',
    saved: 'Salvato nella bozza',
  }[status.kind]
  return (
    <p className="mb-3 h-4 text-meta text-muted-foreground" aria-live="polite" data-testid="editor-status" data-status={status.kind}>
      {label}
      {status.kind === 'saved' && status.final && ' · il documento finale va ricreato con la fase Documento'}
    </p>
  )
}

const linkButton = 'font-semibold text-link underline-offset-2 hover:underline'

/**
 * Modifiche che RT non sa rimettere nella bozza: una riga sola, con Altre info (dove e perché,
 * più le regole del formato), Ripristina e Scarica e ripristina. Finché resta così non salva.
 */
function Incompatible({ problems, onGoToLine, onRestore, onDownloadAndRestore }: {
  problems: Problem[]
  onGoToLine: (line: number) => void
  onRestore: () => void
  onDownloadAndRestore: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-3 rounded-md border border-danger/40 px-3 py-2 text-meta" role="alert" data-testid="document-edit-errors">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">Modifiche non compatibili con RT: non le salvo.</span>
        <button type="button" className={linkButton} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? 'Meno info' : 'Altre info'}
        </button>
        <button type="button" className={linkButton} onClick={onRestore}>Ripristina</button>
        <button type="button" className={linkButton} onClick={onDownloadAndRestore}>Scarica e ripristina</button>
      </p>
      {open && (
        <div className="mt-2 flex flex-col gap-2" data-testid="document-edit-help">
          <ul className="flex flex-col gap-0.5">
            {problems.map((p, i) => (
              <li key={`${p.line ?? 'x'}-${i}`}>
                {p.line != null && (
                  <button type="button" className="font-semibold underline" onClick={() => onGoToLine(p.line!)}>Riga {p.line}</button>
                )}
                {p.line != null ? ': ' : ''}
                {p.message}
              </li>
            ))}
          </ul>
          <div className="text-muted-foreground">
            <p>
              RT tiene il testo di ogni unità a parte, legato all'audio e alla scaletta: revisione, recall,
              Studio e arricchimento lavorano per unità. Per questo la struttura del documento non cambia:
            </p>
            <ul className="mt-1 list-disc pl-5">
              <li><code>## 1. Titolo</code> apre una sezione, <code>### 1.1 Titolo</code> un'unità: i livelli dei titoli e i numeri restano quelli; i titoli si possono riscrivere.</li>
              <li>Sezioni e unità non si aggiungono, non si tolgono e non si spostano.</li>
              <li>Sotto il titolo di ogni unità c'è il suo timecode (triplo clic per cambiarlo); non va oltre la durata dell'audio e viene dopo quello dell'unità precedente.</li>
              <li>Il testo sta dentro le unità: sotto il titolo di una sezione vanno solo immagini; un'unità non resta vuota.</li>
              <li>Dentro un'unità il testo è libero: paragrafi, grassetto, elenchi, link, immagini della lezione.</li>
            </ul>
            <p className="mt-1">
              Ripristina torna all'ultima versione salvata. Scarica e ripristina salva il Markdown com'è adesso in un
              file .md, per continuare in un altro editor, e poi ripristina.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
