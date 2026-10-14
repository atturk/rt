import { useState, useRef, useEffect } from 'react'
import { AlertCircle, Check, CheckCircle2, Clock, Copy, ExternalLink, HelpCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'
import { useIsPhone } from '@/lib/phone'
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
  const popupRef = useRef<HTMLDivElement>(null)

  const stylePos: { left?: number; top?: number } = {}
  if (open && !isPhone && anchorRect) {
    const width = Math.min(440, typeof window !== 'undefined' ? window.innerWidth - 24 : 440)
    let left = anchorRect.left + anchorRect.width / 2 - width / 2
    left = Math.max(12, Math.min(left, (typeof window !== 'undefined' ? window.innerWidth : 800) - width - 12))
    let top = anchorRect.bottom + 8
    if (typeof window !== 'undefined' && top + 340 > window.innerHeight) {
      top = Math.max(60, anchorRect.top - 350)
    }
    stylePos.left = left
    stylePos.top = top
  }

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
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
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

  return (
    <div
      ref={popupRef}
      role="dialog"
      aria-label={isVerifica ? 'Verifica' : 'Chiedi'}
      data-testid="study-note-popup"
      data-kind={effectiveKind}
      style={!isPhone && stylePos.left !== undefined ? { left: `${stylePos.left}px`, top: `${stylePos.top}px` } : undefined}
      className={
        isPhone
          ? 'fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-2xl border-t bg-card p-4 shadow-panel animate-in slide-in-from-bottom'
          : 'fixed z-50 w-[440px] max-w-[calc(100vw-32px)] rounded-xl border bg-card p-4 shadow-panel'
      }
    >
      {/* Intestazione */}
      <div className="mb-3 flex items-center justify-between gap-2 border-b border-border/60 pb-2.5">
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
        <IconButton label="Chiudi · Esc" icon={X} onClick={onClose} data-testid="study-note-close" />
      </div>

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
        className={`mb-3 rounded-md border p-2.5 text-body italic text-foreground ${
          !isVerifica ? 'border-[#c7761a]/30 bg-[#c7761a]/5' : 'border-border/60 bg-muted/40'
        }`}
        data-testid="study-note-quote"
      >
        {effectiveQuote}
      </div>

      {/* Stato 1: Inserimento richiesta prima dell'invio */}
      {!note && !isWaiting && (
        <>
          <div className="mb-3">
            <textarea
              className="w-full resize-none rounded-md border border-input bg-background p-2.5 text-body placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
              rows={3}
              placeholder={isVerifica ? 'Cosa vuoi verificare?' : 'Cosa vuoi chiedere?'}
              aria-label="Richiesta facoltativa"
              data-testid="study-note-input"
              value={requestText}
              onChange={(e) => setRequestText(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-meta text-muted-foreground">⌘↵ per inviare</span>
            <Button size="sm" onClick={() => void handleSend()} data-testid="study-note-submit">
              {isVerifica ? 'Verifica' : 'Chiedi'}
            </Button>
          </div>
        </>
      )}

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
        <div data-testid="study-note-result">
          {note.request && (
            <div className="mb-2.5 text-meta">
              <span className="font-semibold">Richiesta:</span> {note.request}
            </div>
          )}

          {verdict && VERDICT_INFO[verdict] && (
            <div className="mb-2.5">
              <Badge tone={VERDICT_INFO[verdict].tone} data-testid="study-note-verdict">
                {VERDICT_INFO[verdict].label}
              </Badge>
            </div>
          )}

          <div className="my-2.5 text-body whitespace-pre-wrap leading-relaxed text-foreground" data-testid="study-note-answer">
            {resp?.spiegazione}
          </div>

          {fix && (
            <div className={`my-3 rounded-lg border p-3 ${isApplied ? 'border-ok/40 bg-ok/5' : 'border-border bg-muted/30'}`} data-testid="study-note-fix-box">
              <div className="mb-1.5 flex items-center justify-between text-meta font-medium">
                <span className={isApplied ? 'text-ok' : 'text-foreground'}>
                  {isApplied ? 'Correzione applicata' : 'Correzione proposta'}
                </span>
                {!isApplied && (
                  <Tooltip content="Applica la correzione al testo (come ✓ nella Verifica con LLM)">
                    {(trigger) => (
                      <Button
                        {...trigger}
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1 px-2.5 text-ok hover:text-ok"
                        disabled={!canApply || isApplying}
                        onClick={() => onApply && void onApply(note.id)}
                        data-testid="study-note-apply"
                      >
                        <Check className="size-3.5" aria-hidden /> Applica
                      </Button>
                    )}
                  </Tooltip>
                )}
              </div>
              <div className="font-mono text-[13px] text-foreground">{fix}</div>
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

          <div className="mt-3 flex items-center justify-between border-t border-border/60 pt-2 text-meta text-muted-foreground">
            <span>
              Salvata in Dettagli › Verifiche e domande
              {note.cost ? ` · $${note.cost.toFixed(3)}` : ''}
            </span>
            <div className="flex items-center gap-1">
              {copied && <span className="text-ok text-meta">Copiata!</span>}
              <IconButton label="Copia la risposta" icon={Copy} onClick={handleCopy} data-testid="study-note-copy" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
