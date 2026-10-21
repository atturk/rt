import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, Check, CheckCircle2, Clock, Copy, ExternalLink, HelpCircle, Maximize2, Minimize2, SendHorizontal, ChevronsUpDown, X } from 'lucide-react'
import { IconAnchor, IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'
import { useIsPhone } from '@/lib/phone'
import { useStudyNoteWindow } from './studyNoteWindow'
import { useStudyNoteSheet } from './studyNoteSheet'
import { renderDelimitedMath } from '@/lib/math'
import { MathText } from '@/components/MathText'
import type { StudyNote } from '@/api/studyNotes'

export interface StudyNotePopupProps {
  open: boolean
  onClose: () => void
  kind: 'verifica' | 'chiedi'
  unitId: string
  quote: string
  note?: StudyNote | null
  onSend?: (request: string) => Promise<void>
  onApply?: (noteId: number) => Promise<void>
  isWaiting?: boolean
  isApplying?: boolean
  anchorRect?: DOMRect | null
}

const VERDICT_INFO: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  corretto: { label: 'Corretto', tone: 'success' },
  impreciso: { label: 'Impreciso', tone: 'warning' },
  errato: { label: 'Errato', tone: 'danger' },
  non_verificabile: { label: 'Non verificabile', tone: 'neutral' },
}

export function StudyNotePopup({
  open,
  onClose,
  kind,
  unitId,
  quote,
  note,
  onSend,
  onApply,
  isWaiting = false,
  isApplying = false,
  anchorRect,
}: StudyNotePopupProps) {
  const isPhone = useIsPhone()
  const [requestText, setRequestText] = useState('')
  const [copied, setCopied] = useState(false)
  const [quoteExpanded, setQuoteExpanded] = useState(false)
  const windowState = useStudyNoteWindow(open, isPhone, anchorRect)
  const { ref: popupRef, frame } = windowState
  const sheet = useStudyNoteSheet(open, isPhone, (note?.response?.spiegazione?.length ?? 0) > 600)
  const resultRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (open && resultRef.current) void renderDelimitedMath(resultRef.current)
  }, [open, note?.spiegazione_html, note?.correzione_html, note?.response?.spiegazione])

  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if (!open) return
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleGlobalKey)
    return () => window.removeEventListener('keydown', handleGlobalKey)
  }, [open, onClose])

  if (!open) return null

  const resp = note?.response as { esito?: string; spiegazione?: string; correzione?: string; sources?: Array<{ title?: string; url?: string }> } | undefined
  const anchorObj = note?.anchor as { quote?: string } | undefined

  const handleSend = async () => {
    if (!onSend || isWaiting) return
    await onSend(requestText.trim())
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.nativeEvent.keyCode !== 229) {
      e.preventDefault()
      void handleSend()
    }
  }

  const handleCopy = () => {
    const textToCopy = resp?.spiegazione || ''
    if (textToCopy) {
      void navigator.clipboard?.writeText(textToCopy)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const effectiveKind = note?.kind || kind
  const isVerifica = effectiveKind === 'verifica'
  const effectiveUnit = note?.unit_id || unitId
  const effectiveQuote = String(anchorObj?.quote || quote || '')
  const verdict = resp?.esito
  const fix = resp?.correzione
  const isApplied = !!note?.applied_decision_id
  const canApply = isVerifica && !!fix && note?.anchor_state === 'trovata' && !isApplied

  return createPortal(
    <div
      ref={popupRef}
      role="dialog"
      aria-label={isVerifica ? 'Verifica' : 'Chiedi'}
      data-testid="study-note-popup"
      data-kind={effectiveKind}
      data-sheet-level={isPhone ? sheet.level : undefined}
      style={!isPhone ? { left: frame.x, top: frame.y, width: frame.width, height: frame.height ?? undefined, maxHeight: frame.docked ? '100dvh' : 'calc(100dvh - 24px)', minHeight: 'min(240px, calc(100dvh - 24px))' } : sheet.style}
      className={
        isPhone
          ? 'fixed z-[55] flex flex-col overflow-hidden rounded-t-2xl border-t bg-card shadow-panel animate-in slide-in-from-bottom'
          : 'fixed z-50 flex flex-col overflow-hidden rounded-xl border bg-card shadow-panel'
      }
    >
      {/* Intestazione */}
      {isPhone && <div role="slider" tabIndex={0} aria-label="Altezza del foglio" aria-valuemin={0} aria-valuemax={2} aria-valuenow={sheet.level} aria-valuetext={['Bassa', 'Metà', 'Piena'][sheet.level]}
        className="flex h-6 shrink-0 touch-none items-center justify-center focus-visible:outline-2 focus-visible:outline-ring" data-testid="study-note-handle" onPointerDown={sheet.begin}
        onKeyDown={(event) => { if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); sheet.step(event.key === 'ArrowUp' ? 1 : -1) } }}>
        <span className="h-1 w-9 rounded-full bg-muted-foreground/50" />
      </div>}
      <div className="flex shrink-0 touch-none select-none items-center justify-between gap-2 border-b border-border/60 p-3 md:cursor-move" data-testid="study-note-header" onPointerDown={(event) => windowState.begin(event)} onDoubleClick={() => { if (!isPhone) windowState.reset() }}>
        <div className="flex items-center gap-2">
          {isVerifica ? (
            <CheckCircle2 className="size-4.5 text-[#155f52]" aria-hidden />
          ) : (
            <HelpCircle className="size-4.5 text-[#c7761a]" aria-hidden />
          )}
          <span className="font-semibold text-foreground">{isVerifica ? 'Verifica' : 'Chiedi'}</span>
          <span className="text-meta text-muted-foreground">· unità {effectiveUnit}</span>
          {note?.precedente && (
            <Tooltip content="Precedente all'ultima aggiunta di fonti">
              {(trigger) => (
                <span
                  {...trigger}
                  className="inline-flex shrink-0 items-center text-muted-foreground"
                  data-testid="note-precedente-icon"
                >
                  <Clock className="size-4" aria-hidden />
                </span>
              )}
            </Tooltip>
          )}
        </div>
        <div className="flex items-center">
          {!isPhone && <IconButton label={frame.docked ? 'Torna al popup' : 'Allarga a pannello'} icon={frame.docked ? Minimize2 : Maximize2} onClick={windowState.dock} />}
          <IconButton label="Chiudi · Esc" icon={X} onClick={onClose} data-testid="study-note-close" />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3" data-testid="study-note-body">
      {/* Corpo: avvisi di ritrovamento se la nota è salvata */}
      {note && note.anchor_state === 'cambiata' && (
        <div className="mb-3 flex items-start gap-2 rounded-md bg-warning/10 p-2 text-meta text-warning">
          <AlertCircle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span>Il testo è cambiato dopo la {isVerifica ? 'verifica' : 'domanda'}. Adesso: “{note.current_quote}”</span>
        </div>
      )}
      {note && note.anchor_state === 'non_ritrovata' && (
        <div className="mb-3 flex items-start gap-2 rounded-md bg-destructive/10 p-2 text-meta text-destructive">
          <AlertCircle className="size-4 shrink-0 mt-0.5" aria-hidden />
          <span>Passaggio non ritrovato. L'ultima volta era nell'unità {note.unit_id}.</span>
        </div>
      )}

      {/* Citazione selezionata */}
      <div
        className={`mb-3 flex items-start gap-1 rounded-md border p-2.5 text-body italic text-foreground ${
          !isVerifica ? 'border-[#c7761a]/30 bg-[#c7761a]/5' : 'border-border/60 bg-muted/40'
        }`}
        data-testid="study-note-quote"
      >
        <span className={`min-w-0 flex-1 ${quoteExpanded ? '' : 'line-clamp-2'}`}><MathText text={effectiveQuote} /></span>
        <IconButton label={quoteExpanded ? 'Riduci la citazione' : 'Mostra tutto'} icon={ChevronsUpDown} onClick={() => setQuoteExpanded((value) => !value)} className="-my-1 -mr-1 shrink-0 not-italic" />
      </div>

      {/* Stato 2: Attesa risposta */}
      {!note && isWaiting && (
        <div className="py-2" data-testid="study-note-waiting">
          {requestText && (
            <div className="mb-3 text-meta">
              <span className="font-semibold">Richiesta:</span> {requestText}
            </div>
          )}
          <div className="my-3 flex items-center gap-2.5 text-meta text-muted-foreground">
            <span className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-hidden />
            <span>{isVerifica ? 'Verifico con il modello della revisione…' : 'Preparo la spiegazione con il modello della revisione…'}</span>
          </div>
          <div className="space-y-1.5 py-1">
            <div className="h-2 w-5/6 animate-pulse rounded bg-muted" />
            <div className="h-2 w-3/4 animate-pulse rounded bg-muted" />
          </div>
          <p className="mt-3 text-meta text-muted-foreground">Puoi chiudere: la risposta arriva lo stesso e resta nella lezione.</p>
        </div>
      )}

      {/* Stato 3: Risposta pronta / visualizzazione nota */}
      {note && (
        <div ref={resultRef} data-testid="study-note-result">
          {note.request && (
            <div className="mb-2.5 text-meta">
              <span className="font-semibold">Richiesta:</span> <MathText text={note.request} />
            </div>
          )}

          {verdict && VERDICT_INFO[verdict] && (
            <div className="mb-2.5">
              <Badge tone={VERDICT_INFO[verdict].tone} data-testid="study-note-verdict">
                {VERDICT_INFO[verdict].label}
              </Badge>
            </div>
          )}

          <div className="rt-document rt-reading my-2.5 text-body leading-relaxed text-foreground" data-testid="study-note-answer"
            {...(note.spiegazione_html ? { dangerouslySetInnerHTML: { __html: note.spiegazione_html } } : { children: resp?.spiegazione })} />

          {fix && (
            <div className={`my-3 rounded-lg border p-3 ${isApplied ? 'border-ok/40 bg-ok/5' : 'border-border bg-muted/30'}`} data-testid="study-note-fix-box">
              <div className="mb-1.5 flex items-center justify-between text-meta font-medium">
                <span className={isApplied ? 'text-ok' : 'text-foreground'}>
                  {isApplied ? 'Correzione applicata' : 'Correzione proposta'}
                </span>
                {!isApplied && (
                  <IconButton label="Applica la correzione al testo" icon={Check} unavailable={!canApply || isApplying ? 'Correzione non applicabile' : null} onClick={() => onApply && void onApply(note.id)} data-testid="study-note-apply" />
                )}
              </div>
              <div className="rt-document text-body text-foreground"
                {...(note.correzione_html ? { dangerouslySetInnerHTML: { __html: note.correzione_html } } : { children: fix })} />
            </div>
          )}

          {resp?.sources && resp.sources.length > 0 && (
            <div className="my-2.5" data-testid="study-note-sources">
              <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Fonti</span>
              <div className="mt-1 flex flex-col gap-1.5">
                {resp.sources.map((src: { title?: string; url?: string }, idx: number) => (
                  <a
                    key={idx}
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-meta text-primary hover:underline break-all"
                  >
                    <ExternalLink className="size-3 shrink-0" aria-hidden />
                    <span>{src.title || src.url}</span>
                  </a>
                ))}
              </div>
            </div>
          )}


        </div>
      )}
      </div>
      {/* Fondo fisso: resta raggiungibile mentre il centro scorre. */}
      {!note && !isWaiting && (
        <div className="shrink-0 border-t bg-card p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]" data-testid="study-note-composer">
          <div className="flex items-end gap-2 rounded-lg border bg-muted/40 p-2">
            <textarea className="min-w-0 flex-1 resize-none bg-transparent text-body focus-visible:outline-2 focus-visible:outline-ring"
              rows={2} placeholder={isVerifica ? 'Cosa vuoi verificare?' : 'Cosa vuoi chiedere?'} aria-label="Richiesta facoltativa"
              data-testid="study-note-input" value={requestText} onChange={(e) => setRequestText(e.target.value)} onKeyDown={handleKeyDown} autoFocus />
            <IconButton label={isVerifica ? 'Verifica' : 'Chiedi'} icon={SendHorizontal} variant="solid" onClick={() => void handleSend()} data-testid="study-note-submit" />
          </div>
          <p className="mt-1 text-meta text-muted-foreground">↵ invia · ⇧↵ va a capo</p>
        </div>
      )}
      {note && (
        <div className="flex shrink-0 items-center justify-end gap-1 border-t bg-card px-3 py-2 text-meta text-muted-foreground">
          {note.cost ? <span className="mr-auto">${note.cost.toFixed(3)}</span> : null}
          {copied && <span className="text-ok">Copiata!</span>}
          <IconAnchor label="Salvata in Dettagli › Verifiche e domande" icon={CheckCircle2} href={`/lezioni/${note.lesson_id}?panel=note&note=${note.id}`} />
          <IconButton label="Copia la risposta" icon={Copy} onClick={handleCopy} data-testid="study-note-copy" />
        </div>
      )}
      {!isPhone && !frame.docked && (['n', 'e', 's', 'w', 'se'] as const).map((edge) => (
        <div key={edge} aria-hidden data-testid={`study-note-resize-${edge}`} onPointerDown={(event) => windowState.begin(event, edge)}
          className={`absolute touch-none ${edge === 'n' ? 'inset-x-3 top-0 h-1 cursor-ns-resize' : edge === 's' ? 'inset-x-3 bottom-0 h-1 cursor-ns-resize' : edge === 'e' ? 'inset-y-3 right-0 w-1 cursor-ew-resize' : edge === 'w' ? 'inset-y-3 left-0 w-1 cursor-ew-resize' : 'bottom-0 right-0 size-3 cursor-nwse-resize border-b-2 border-r-2 border-muted-foreground/40'}`} />
      ))}
    </div>, document.body,
  )
}
