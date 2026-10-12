import { useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  HelpCircle,
  Trash2,
} from 'lucide-react'
import { useStudyNotes, useApplyStudyNote, useDeleteStudyNote, type StudyNote } from '@/api/studyNotes'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { ConfirmDialog } from '@/components/ui/dialog'
import { formatDateTime } from '@/lib/format'

import { EDITOR_SCROLL_EVENT } from '@/lib/lessonPanel'

export interface StudyNotesPanelProps {
  lessonId: number
  selectedNoteId?: number | null
  onSelectNote?: (noteId: number | null) => void
  onGotoUnit?: (unitId: string) => void
}

const VERDICT_INFO: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  corretto: { label: 'Corretto', tone: 'success' },
  impreciso: { label: 'Impreciso', tone: 'warning' },
  errato: { label: 'Errato', tone: 'danger' },
  non_verificabile: { label: 'Non verificabile', tone: 'neutral' },
}

export function StudyNotesPanel({
  lessonId,
  selectedNoteId,
  onSelectNote,
  onGotoUnit,
}: StudyNotesPanelProps) {
  const { data: notes = [], isLoading } = useStudyNotes(lessonId)
  const applyMutation = useApplyStudyNote(lessonId)
  const deleteMutation = useDeleteStudyNote(lessonId)

  const [internalNoteId, setInternalNoteId] = useState<number | null>(null)
  const activeNoteId = selectedNoteId !== undefined ? selectedNoteId : internalNoteId
  const [filter, setFilter] = useState<'tutte' | 'verifica' | 'chiedi'>('tutte')
  const [copied, setCopied] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)

  const selectNote = (id: number | null) => {
    setInternalNoteId(id)
    onSelectNote?.(id)
  }

  const activeNote = notes.find((n) => n.id === activeNoteId) ?? null

  const handleCopy = (text: string) => {
    if (!text) return
    void navigator.clipboard?.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleGoto = (unitId: string) => {
    if (onGotoUnit) {
      onGotoUnit(unitId)
    } else {
      window.dispatchEvent(new CustomEvent(EDITOR_SCROLL_EVENT, { detail: { unitId } }))
    }
  }

  // Vista 1: Dettaglio di una singola voce
  if (activeNote) {
    const isVerifica = activeNote.kind === 'verifica'
    const resp = activeNote.response as { esito?: string; spiegazione?: string; correzione?: string } | undefined
    const anchorObj = activeNote.anchor as { quote?: string } | undefined
    const quote = String(anchorObj?.quote || activeNote.current_quote || '')
    const verdict = resp?.esito
    const fix = resp?.correzione
    const isApplied = !!activeNote.applied_decision_id
    const canApply = isVerifica && !!fix && activeNote.anchor_state === 'trovata' && !isApplied

    return (
      <div className="flex flex-col gap-3 text-body" data-testid="study-notes-detail">
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 px-2 text-meta text-muted-foreground hover:text-foreground"
            onClick={() => selectNote(null)}
            data-testid="study-notes-back"
          >
            <ArrowLeft className="size-4" aria-hidden />
            Torna alla lista
          </Button>
          <span className="text-meta font-medium text-foreground flex items-center gap-1.5">
            <span>{isVerifica ? 'Verifica' : 'Chiedi'} · unità {activeNote.unit_id}</span>
            {activeNote.precedente && (
              <Tooltip content="Precedente all'ultima aggiunta di fonti">
                {(trigger) => (
                  <span
                    {...trigger}
                    className="inline-flex shrink-0 items-center text-muted-foreground"
                    data-testid="note-precedente-icon"
                  >
                    <Clock className="size-3.5" aria-hidden />
                  </span>
                )}
              </Tooltip>
            )}
          </span>
        </div>

        {activeNote.anchor_state === 'cambiata' && (
          <div className="flex items-start gap-2 rounded-md bg-warning/10 p-2.5 text-meta text-warning">
            <AlertCircle className="size-4 shrink-0 mt-0.5" aria-hidden />
            <span>
              Il testo è cambiato dopo la {isVerifica ? 'verifica' : 'domanda'}. Adesso: “{activeNote.current_quote}”
            </span>
          </div>
        )}

        {activeNote.anchor_state === 'non_ritrovata' && (
          <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-2.5 text-meta text-destructive">
            <AlertCircle className="size-4 shrink-0 mt-0.5" aria-hidden />
            <span>Passaggio non ritrovato. L'ultima volta era nell'unità {activeNote.unit_id}.</span>
          </div>
        )}

        <div>
          <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Testo di partenza</span>
          <div className="mt-1 rounded-md border border-border/60 bg-muted/30 p-2.5 italic text-foreground" data-testid="detail-quote">
            {quote}
          </div>
        </div>

        {activeNote.request && (
          <div>
            <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Richiesta</span>
            <div className="mt-1 text-meta text-foreground" data-testid="detail-request">
              {activeNote.request}
            </div>
          </div>
        )}

        {verdict && VERDICT_INFO[verdict] && (
          <div>
            <Badge tone={VERDICT_INFO[verdict].tone} data-testid="detail-verdict">
              {VERDICT_INFO[verdict].label}
            </Badge>
          </div>
        )}

        <div>
          <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Risposta</span>
          <div className="mt-1 whitespace-pre-wrap text-body leading-relaxed text-foreground" data-testid="detail-answer">
            {resp?.spiegazione}
          </div>
        </div>

        {fix && (
          <div className={`rounded-lg border p-3 ${isApplied ? 'border-ok/40 bg-ok/5' : 'border-border bg-muted/30'}`} data-testid="detail-fix">
            <div className="mb-1.5 flex items-center justify-between text-meta font-medium">
              <span className={isApplied ? 'text-ok' : 'text-foreground'}>
                {isApplied ? 'Correzione applicata' : 'Correzione proposta'}
                {!isApplied && activeNote.anchor_state !== 'trovata' && ' · non applicabile'}
              </span>
              {!isApplied && (
                <Tooltip content="Applica la correzione al testo (come ✓ nella Verifica con LLM)">
                  {(trigger) => (
                    <Button
                      {...trigger}
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1 px-2.5 text-ok hover:text-ok"
                      disabled={!canApply || applyMutation.isPending}
                      onClick={() => void applyMutation.mutate(activeNote.id)}
                      data-testid="detail-apply"
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

        <div className="text-meta text-muted-foreground">
          {activeNote.created_at ? formatDateTime(activeNote.created_at) : ''}
          {activeNote.cost ? ` · $${activeNote.cost.toFixed(3)}` : ''}
          {activeNote.model ? ` · ${activeNote.model}` : ''}
        </div>

        <div className="flex items-center justify-between border-t border-border/60 pt-3">
          <div className="flex items-center gap-1.5">
            <Tooltip content={`Vai all'unità ${activeNote.unit_id}`}>
              {(trigger) => (
                <Button
                  {...trigger}
                  variant="outline"
                  size="sm"
                  className="gap-1.5 text-meta"
                  onClick={() => handleGoto(activeNote.unit_id)}
                  data-testid="detail-goto"
                >
                  <ExternalLink className="size-3.5" aria-hidden /> Vai all'unità
                </Button>
              )}
            </Tooltip>
            <Tooltip content="Copia la risposta">
              {(trigger) => (
                <IconButton
                  {...trigger}
                  label="Copia la risposta"
                  icon={Copy}
                  onClick={() => handleCopy(resp?.spiegazione || '')}
                  data-testid="detail-copy"
                />
              )}
            </Tooltip>
            {copied && <span className="text-meta text-ok">Copiata!</span>}
          </div>
          <IconButton
            label="Elimina la voce"
            icon={Trash2}
            className="text-danger hover:text-danger"
            onClick={() => setConfirmDeleteId(activeNote.id)}
            data-testid="detail-delete"
          />
        </div>

        <ConfirmDialog
          open={confirmDeleteId === activeNote.id}
          title="Eliminare questa voce?"
          confirmLabel="Elimina"
          confirmDisabled={deleteMutation.isPending}
          onCancel={() => setConfirmDeleteId(null)}
          onConfirm={() => {
            deleteMutation.mutate(activeNote.id, {
              onSuccess: () => {
                setConfirmDeleteId(null)
                selectNote(null)
              },
            })
          }}
        >
          <p>La voce verrà eliminata dall'elenco. Eventuali correzioni già applicate restano nel testo.</p>
        </ConfirmDialog>
      </div>
    )
  }

  // Vista 2: Elenco delle voci raggruppate per unità
  const filteredNotes = notes.filter((n) => {
    if (filter === 'tutte') return true
    return n.kind === filter
  })

  // Raggruppamento per unit_id
  const notesByUnit: Record<string, StudyNote[]> = {}
  for (const n of filteredNotes) {
    if (!notesByUnit[n.unit_id]) notesByUnit[n.unit_id] = []
    notesByUnit[n.unit_id].push(n)
  }
  const unitKeys = Object.keys(notesByUnit).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))

  return (
    <div className="flex flex-col gap-3 text-body" data-testid="study-notes-panel">
      {/* Filtro Tutte / Verifiche / Chiedi */}
      <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="Filtro voci">
        {(['tutte', 'verifica', 'chiedi'] as const).map((key) => {
          const label = key === 'tutte' ? 'Tutte' : key === 'verifica' ? 'Verifiche' : 'Chiedi'
          const active = filter === key
          return (
            <button
              key={key}
              type="button"
              className={`flex-1 rounded-md py-1 text-center text-meta font-medium transition-colors ${
                active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              }`}
              aria-pressed={active}
              onClick={() => setFilter(key)}
              data-testid={`filter-${key}`}
            >
              {label}
            </button>
          )
        })}
      </div>

      {isLoading && <p className="text-meta text-muted-foreground">Caricamento voci…</p>}

      {!isLoading && filteredNotes.length === 0 && (
        <p className="py-6 text-center text-meta text-muted-foreground" data-testid="empty-notes-message">
          Nessuna voce salvata. Seleziona un passaggio nello Studio con V (Verifica) o C (Chiedi).
        </p>
      )}

      {!isLoading && (
        <div className="flex flex-col gap-4">
          {unitKeys.map((unitId) => {
            const list = notesByUnit[unitId]
            return (
              <div key={unitId} className="flex flex-col gap-1.5" data-testid={`notes-unit-${unitId}`}>
                <div className="flex items-center justify-between text-meta font-semibold text-foreground">
                  <span>Unità {unitId}</span>
                  <span className="text-muted-foreground">{list.length}</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {list.map((note) => {
                    const isVerifica = note.kind === 'verifica'
                    const resp = note.response as { esito?: string; spiegazione?: string; correzione?: string } | undefined
                    const anchorObj = note.anchor as { quote?: string } | undefined
                    const quote = String(note.current_quote || anchorObj?.quote || '')
                    const verdict = resp?.esito
                    const isApplied = !!note.applied_decision_id

                    return (
                      <button
                        key={note.id}
                        type="button"
                        className="group flex flex-col gap-1 rounded-lg border border-border/70 bg-card p-2.5 text-left transition-colors hover:border-primary/50 hover:bg-muted/30 focus-visible:outline-2 focus-visible:outline-ring"
                        onClick={() => selectNote(note.id)}
                        data-testid={`note-item-${note.id}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            {isVerifica ? (
                              <CheckCircle2 className="size-3.5 shrink-0 text-[#155f52]" aria-hidden />
                            ) : (
                              <HelpCircle className="size-3.5 shrink-0 text-[#c7761a]" aria-hidden />
                            )}
                            <span className="truncate text-meta font-medium text-foreground">
                              {quote}
                            </span>
                            {note.precedente && (
                              <Tooltip content="Precedente all'ultima aggiunta di fonti">
                                {(trigger) => (
                                  <span
                                    {...trigger}
                                    className="inline-flex shrink-0 items-center text-muted-foreground"
                                    data-testid="note-precedente-icon"
                                  >
                                    <Clock className="size-3.5" aria-hidden />
                                  </span>
                                )}
                              </Tooltip>
                            )}
                          </div>
                          {isApplied ? (
                            <Badge tone="success" className="shrink-0 text-[11px]">
                              Applicata
                            </Badge>
                          ) : verdict && VERDICT_INFO[verdict] ? (
                            <Badge tone={VERDICT_INFO[verdict].tone} className="shrink-0 text-[11px]">
                              {VERDICT_INFO[verdict].label}
                            </Badge>
                          ) : null}
                        </div>

                        <div className="flex flex-wrap items-center gap-1 text-[12px] text-muted-foreground">
                          {note.created_at ? <span>{formatDateTime(note.created_at)}</span> : null}
                          {note.request && <span>· con richiesta</span>}
                          {note.anchor_state === 'cambiata' && (
                            <span className="text-warning font-medium">· testo cambiato</span>
                          )}
                          {note.anchor_state === 'non_ritrovata' && (
                            <span className="text-destructive font-medium">· passaggio non ritrovato</span>
                          )}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
