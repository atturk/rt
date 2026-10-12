import { useState, useRef, type DragEvent, type KeyboardEvent } from 'react'
import {
  FileText,
  GripVertical,
  Mic,
  Paperclip,
  Plus,
  RotateCw,
  Star,
  Undo2,
  X,
} from 'lucide-react'
import { errorMessage } from '@/api/client'
import {
  sourcesApi,
  useDeleteSource,
  useReorderSources,
  useRestoreVersion,
  useSetPrimarySource,
  useSources,
  useVersions,
  type LessonVersion,
  type SourceItem,
} from '@/api/sources'
import { Alert } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { formatSourceSize, formatVersionDate } from '@/lib/sourcesFormat'
import { cn } from '@/lib/utils'

export function SourcesSection({ lessonId }: { lessonId: number }) {
  const sourcesQuery = useSources(lessonId)
  const versionsQuery = useVersions(lessonId)
  const reorderMutation = useReorderSources(lessonId)
  const setPrimaryMutation = useSetPrimarySource(lessonId)
  const deleteMutation = useDeleteSource(lessonId)
  const restoreMutation = useRestoreVersion(lessonId)

  const [menuOpen, setMenuOpen] = useState(false)
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  // Modale per inserire testo appunti
  const [notesModalOpen, setNotesModalOpen] = useState(false)
  const [notesText, setNotesText] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  // Dialog di conferma per azioni che richiedono ricostruzione
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    title: string
    description: string
    confirmLabel: string
    onConfirm: () => void
  } | null>(null)

  const audioInputRef = useRef<HTMLInputElement>(null)
  const materialsInputRef = useRef<HTMLInputElement>(null)

  const sourcesView = sourcesQuery.data
  const sources = sourcesView?.sources ?? []
  const hasAudio = sources.some((s) => s.tipo === 'audio')
  const audioSources = sources.filter((s) => s.tipo === 'audio')

  // Upload handlers
  const handleAudioSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setActionError(null)
    try {
      await sourcesApi.addAudio(lessonId, file)
      sourcesQuery.refetch()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      if (audioInputRef.current) audioInputRef.current.value = ''
      setMenuOpen(false)
    }
  }

  const handleMaterialsSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setActionError(null)
    try {
      await sourcesApi.addMaterials(lessonId, files)
      sourcesQuery.refetch()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      if (materialsInputRef.current) materialsInputRef.current.value = ''
      setMenuOpen(false)
    }
  }

  const handleNotesSubmit = async () => {
    const trimmed = notesText.trim()
    if (!trimmed) return
    setActionError(null)
    try {
      await sourcesApi.addNotes(lessonId, trimmed)
      setNotesText('')
      setNotesModalOpen(false)
      sourcesQuery.refetch()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setMenuOpen(false)
    }
  }

  // Reorder logic
  const applyAudioReorder = (fromAudioIdx: number, toAudioIdx: number) => {
    if (fromAudioIdx === toAudioIdx) return
    const newAudios = [...audioSources]
    const [moved] = newAudios.splice(fromAudioIdx, 1)
    newAudios.splice(toAudioIdx, 0, moved)

    const nonAudioSources = sources.filter((s) => s.tipo !== 'audio')
    const newAllSources = [...newAudios, ...nonAudioSources]
    const newIds = newAllSources.map((s) => s.id)

    const execute = () => {
      reorderMutation.mutate(newIds, {
        onError: (err) => setActionError(errorMessage(err)),
      })
    }

    // Se spostiamo parti già usate, chiedi conferma
    if (moved.usata) {
      setConfirmDialog({
        open: true,
        title: "Cambiare l'ordine delle registrazioni?",
        description:
          "La lezione dovrà essere ricostruita: la scaletta si rifà da zero. Finché non premi Ricostruisci puoi tornare indietro, e se rimetti tutto com'era la riga sparisce. Lo studio resta, segnato come precedente dove l'unità cambia.",
        confirmLabel: 'Cambia',
        onConfirm: () => {
          setConfirmDialog(null)
          execute()
        },
      })
    } else {
      execute()
    }
  }

  const handleDragStart = (e: DragEvent, audioIdx: number) => {
    setDraggedIndex(audioIdx)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: DragEvent, audioIdx: number) => {
    e.preventDefault()
    if (draggedIndex !== null && draggedIndex !== audioIdx) {
      setDragOverIndex(audioIdx)
    }
  }

  const handleDrop = (e: DragEvent, audioIdx: number) => {
    e.preventDefault()
    if (draggedIndex !== null) {
      applyAudioReorder(draggedIndex, audioIdx)
    }
    setDraggedIndex(null)
    setDragOverIndex(null)
  }

  const handleGripKeyDown = (e: KeyboardEvent, audioIdx: number) => {
    if (e.key === 'ArrowUp' && audioIdx > 0) {
      e.preventDefault()
      applyAudioReorder(audioIdx, audioIdx - 1)
    } else if (e.key === 'ArrowDown' && audioIdx < audioSources.length - 1) {
      e.preventDefault()
      applyAudioReorder(audioIdx, audioIdx + 1)
    }
  }

  // Primary source logic
  const handleSelectPrimary = (source: SourceItem) => {
    if (sourcesView?.principale === source.id) return
    const execute = () => {
      setPrimaryMutation.mutate(source.id, {
        onError: (err) => setActionError(errorMessage(err)),
      })
    }

    // Se la lezione ha già uno stato usato e cambiamo la principale, chiedi conferma
    if (sourcesView?.principale_usato) {
      setConfirmDialog({
        open: true,
        title: "Usare un'altra fonte come principale?",
        description:
          "La lezione dovrà essere ricostruita: la scaletta si rifà da zero. Finché non premi Ricostruisci puoi tornare indietro, e se rimetti tutto com'era la riga sparisce. Lo studio resta, segnato come precedente dove l'unità cambia.",
        confirmLabel: 'Cambia',
        onConfirm: () => {
          setConfirmDialog(null)
          execute()
        },
      })
    } else {
      execute()
    }
  }

  // Reset to original used order and primary
  const handleResetToUsed = () => {
    if (!sourcesView) return
    if (sourcesView.ordine_usato) {
      reorderMutation.mutate(sourcesView.ordine_usato)
    }
    if (sourcesView.principale_usato) {
      setPrimaryMutation.mutate(sourcesView.principale_usato)
    }
  }

  // Restore version confirmation
  const handleRestoreVersionClick = (v: LessonVersion) => {
    setConfirmDialog({
      open: true,
      title: 'Ripristinare questa versione?',
      description:
        'Verrà creata una fotografia dello stato attuale, quindi potrai annullare il ripristino se necessario. I dati di studio non vengono cancellati.',
      confirmLabel: 'Ripristina',
      onConfirm: () => {
        setConfirmDialog(null)
        restoreMutation.mutate(v.id, {
          onError: (err) => setActionError(errorMessage(err)),
        })
      },
    })
  }

  let audioCounter = 0

  return (
    <div className="flex flex-col gap-3" data-testid="sources-section">
      {/* Intestazione Fonti */}
      <div className="relative flex items-center justify-between">
        <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">
          Fonti
        </span>
        <div className="relative">
          <IconButton
            id="plus-sources"
            icon={Plus}
            label="Aggiungi fonte"
            aria-expanded={menuOpen}
            active={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          />
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full z-20 mt-1 flex min-w-56 flex-col gap-1 rounded-lg border bg-card p-1 shadow-lg text-body"
            >
              <button
                type="button"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-muted"
                onClick={() => audioInputRef.current?.click()}
              >
                <Mic className="size-4 shrink-0 text-muted-foreground" />
                Parte di registrazione
              </button>
              <button
                type="button"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-muted"
                onClick={() => {
                  setMenuOpen(false)
                  setNotesModalOpen(true)
                }}
              >
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                Appunti
              </button>
              <button
                type="button"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-muted"
                onClick={() => materialsInputRef.current?.click()}
              >
                <Paperclip className="size-4 shrink-0 text-muted-foreground" />
                Materiali (PDF, slide, foto)
              </button>
            </div>
          )}
        </div>
        <input
          ref={audioInputRef}
          type="file"
          accept=".mp3,.m4a,.wav,.ogg,.aac,.flac,audio/*"
          className="hidden"
          onChange={handleAudioSelected}
        />
        <input
          ref={materialsInputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.heic,.pptx"
          className="hidden"
          onChange={handleMaterialsSelected}
        />
      </div>

      {actionError && <Alert tone="danger">{actionError}</Alert>}

      {/* Banner solo ricostruzione con pulsante "Rimetti com'era" */}
      {sourcesView?.solo_ricostruzione && (
        <div
          className="flex items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-meta text-warning-foreground"
          data-testid="rebuild-required-notice"
        >
          <span>Ordine o fonte principale cambiati: la lezione va ricostruita</span>
          <IconButton
            icon={Undo2}
            label="Rimetti com'era"
            onClick={handleResetToUsed}
          />
        </div>
      )}

      {/* Elenco fonti */}
      {sourcesQuery.isPending && (
        <p className="text-meta text-muted-foreground">Carico le fonti…</p>
      )}

      {sources.length === 0 && !sourcesQuery.isPending && (
        <p className="text-meta text-muted-foreground">Nessuna fonte presente.</p>
      )}

      <div className="flex flex-col gap-1">
        {sources.map((s) => {
          const isAudio = s.tipo === 'audio'
          const audioIdx = isAudio ? audioCounter++ : -1
          const isPrimary = hasAudio
            ? isAudio && audioIdx === 0
            : sourcesView?.principale === s.id
          const sizeText = formatSourceSize(s)

          return (
            <div
              key={s.id}
              data-testid={`source-row-${s.id}`}
              onDragOver={isAudio ? (e) => handleDragOver(e, audioIdx) : undefined}
              onDrop={isAudio ? (e) => handleDrop(e, audioIdx) : undefined}
              className={cn(
                'group relative flex items-center gap-2 rounded-lg px-2 py-1.5 text-body transition-colors hover:bg-muted/60',
                isAudio && dragOverIndex === audioIdx && 'border-2 border-accent',
              )}
            >
              {/* Icona tipo */}
              {s.tipo === 'audio' && <Mic className="size-4 shrink-0 text-muted-foreground" />}
              {s.tipo === 'appunti' && <FileText className="size-4 shrink-0 text-muted-foreground" />}
              {s.tipo === 'materiale' && <Paperclip className="size-4 shrink-0 text-muted-foreground" />}

              {/* Se audio: maniglia e numero */}
              {isAudio && (
                <>
                  <span
                    className="grip flex size-5 cursor-grab items-center justify-center opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                    draggable="true"
                    tabIndex={0}
                    role="button"
                    aria-label={`Riordina ${s.nome}`}
                    data-testid={`grip-${s.id}`}
                    onDragStart={(e) => handleDragStart(e, audioIdx)}
                    onKeyDown={(e) => handleGripKeyDown(e, audioIdx)}
                  >
                    <GripVertical className="size-3.5 text-muted-foreground" />
                  </span>
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-bold tabular-nums">
                    {audioIdx + 1}
                  </span>
                </>
              )}

              {/* Stellina principale */}
              {isPrimary ? (
                <span
                  className="flex size-4 shrink-0 items-center justify-center text-amber-500"
                  title={hasAudio ? 'Principale: la registrazione' : 'Materiale principale'}
                  data-testid="star-primary"
                >
                  <Star className="size-3.5 fill-current" />
                </span>
              ) : !hasAudio ? (
                <button
                  type="button"
                  className="flex size-4 shrink-0 cursor-pointer items-center justify-center text-muted-foreground opacity-0 hover:text-amber-500 group-hover:opacity-100 group-focus-within:opacity-100"
                  aria-label={`Usa ${s.nome} come principale`}
                  data-testid={`star-choose-${s.id}`}
                  onClick={() => handleSelectPrimary(s)}
                >
                  <Star className="size-3.5" />
                </button>
              ) : null}

              {/* Nome */}
              <span className="min-w-0 flex-1 truncate font-medium">{s.nome}</span>

              {/* Misura */}
              {sizeText && (
                <span className="text-meta text-muted-foreground tabular-nums">{sizeText}</span>
              )}

              {/* Puntino fonte nuova non ancora usata */}
              {!s.usata && (
                <span
                  role="img"
                  className="size-1.5 shrink-0 rounded-full bg-amber-500"
                  title="Non ancora usata"
                  aria-label="Non ancora usata"
                  data-testid="source-unused-dot"
                />
              )}

              {/* Pulsante rimuovi X */}
              <IconButton
                icon={X}
                label={`Togli ${s.nome}`}
                className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(s.id)}
              />
            </div>
          )
        })}
      </div>

      {/* Sezione Versioni chiusa di default */}
      <details className="vers group rounded-lg border bg-card p-3" data-testid="versions-details">
        <summary className="flex cursor-pointer items-center justify-between text-body font-semibold">
          <span className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">
            Versioni
          </span>
        </summary>
        <div className="mt-2.5 flex flex-col gap-1.5">
          {versionsQuery.isPending && (
            <p className="text-meta text-muted-foreground">Carico le versioni…</p>
          )}
          {(versionsQuery.data ?? []).map((v) => {
            const modeIcon =
              v.modo === 'extend' ? (
                <span className="text-sm font-bold text-muted-foreground" title="Estendi">
                  +
                </span>
              ) : v.modo === 'rebuild' ? (
                <span title="Ricostruisci">
                  <RotateCw className="size-3.5 text-muted-foreground" />
                </span>
              ) : v.modo === 'restore' ? (
                <span title="Ripristino">
                  <Undo2 className="size-3.5 text-muted-foreground" />
                </span>
              ) : (
                <span className="text-sm font-bold text-muted-foreground" title="Import">
                  •
                </span>
              )

            const added = v.fonti_aggiunte.length ? ` · ${v.fonti_aggiunte.join(', ')}` : ''

            return (
              <div
                key={v.id}
                className="group flex items-center justify-between gap-2 rounded-md px-2 py-1 text-meta hover:bg-muted/50"
                data-testid={`version-row-${v.id}`}
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="flex size-4 shrink-0 items-center justify-center">{modeIcon}</span>
                  <span className="truncate">
                    {formatVersionDate(v.il)}
                    {added}
                  </span>
                </div>
                {v.attuale ? (
                  <span className="text-muted-foreground">attuale</span>
                ) : (
                  <IconButton
                    icon={Undo2}
                    label="Ripristina questa versione"
                    className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                    disabled={restoreMutation.isPending}
                    onClick={() => handleRestoreVersionClick(v)}
                  />
                )}
              </div>
            )
          })}
          {(versionsQuery.data ?? []).length === 0 && !versionsQuery.isPending && (
            <p className="text-meta text-muted-foreground">Nessuna versione registrata.</p>
          )}
        </div>
      </details>

      {/* Modal inserimento appunti */}
      {notesModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="notes-dialog-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="flex w-full max-w-md flex-col gap-3 rounded-xl border bg-card p-4 shadow-xl">
            <b id="notes-dialog-title" className="text-body font-semibold">
              Aggiungi appunti
            </b>
            <textarea
              rows={5}
              placeholder="Incolla o scrivi il testo degli appunti..."
              value={notesText}
              onChange={(e) => setNotesText(e.target.value)}
              className="w-full rounded-md border bg-background p-2.5 text-body focus-visible:outline-2 focus-visible:outline-ring"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border px-3 py-1.5 text-body hover:bg-muted"
                onClick={() => setNotesModalOpen(false)}
              >
                Annulla
              </button>
              <button
                type="button"
                disabled={!notesText.trim()}
                className="rounded-md bg-accent px-3 py-1.5 text-body font-semibold text-accent-foreground disabled:opacity-40"
                onClick={handleNotesSubmit}
              >
                Aggiungi
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog per azioni che rifanno la scaletta */}
      {confirmDialog && (
        <ConfirmDialog
          open={confirmDialog.open}
          title={confirmDialog.title}
          confirmLabel={confirmDialog.confirmLabel}
          onConfirm={confirmDialog.onConfirm}
          onCancel={() => setConfirmDialog(null)}
        >
          {confirmDialog.description}
        </ConfirmDialog>
      )}
    </div>
  )
}
