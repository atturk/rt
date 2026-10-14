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
  useResetSelection,
  useRestoreVersion,
  useSetPrimarySource,
  useSources,
  useSourcesJob,
  useVersions,
  type LessonVersion,
  type SourceItem,
} from '@/api/sources'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { LinkMenuButton } from '@/components/ui/menu'
import { Modal } from '@/components/ui/modal'
import { formatBytes } from '@/lib/jobs'
import { formatSourceSize, formatVersionDate } from '@/lib/sourcesFormat'
import { cn } from '@/lib/utils'

export function SourcesSection({ lessonId }: { lessonId: number }) {
  const sourcesQuery = useSources(lessonId)
  const versionsQuery = useVersions(lessonId)
  const reorderMutation = useReorderSources(lessonId)
  const setPrimaryMutation = useSetPrimarySource(lessonId)
  const deleteMutation = useDeleteSource(lessonId)
  const restoreMutation = useRestoreVersion(lessonId)
  const resetMutation = useResetSelection(lessonId)
  const restoreJob = useSourcesJob(lessonId)

  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  // Modale per inserire testo appunti
  const [notesModalOpen, setNotesModalOpen] = useState(false)
  const [notesText, setNotesText] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  // Upload audio multipli
  const [pendingAudios, setPendingAudios] = useState<File[]>([])
  const [unisciAudio, setUnisciAudio] = useState(true)
  const [uploadingAudio, setUploadingAudio] = useState(false)

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
  const audioSources = sources.filter((s) => s.tipo === 'audio')
  const audioIsPrimary = audioSources.some((s) => s.id === sourcesView?.principale)

  // Upload handlers
  const handleAudioSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    if (audioInputRef.current) audioInputRef.current.value = ''
    if (files.length === 1) {
      setActionError(null)
      try {
        await sourcesApi.addAudio(lessonId, files[0])
        sourcesQuery.refetch()
      } catch (err) {
        setActionError(errorMessage(err))
      }
      return
    }
    setPendingAudios(files)
    setUnisciAudio(true)
  }

  const handleUploadPendingAudios = async () => {
    if (!pendingAudios.length) return
    setUploadingAudio(true)
    setActionError(null)
    try {
      await sourcesApi.addAudio(lessonId, pendingAudios, undefined, unisciAudio)
      setPendingAudios([])
      sourcesQuery.refetch()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setUploadingAudio(false)
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

  // Ordine e principale dell'ultimo aggiornamento, in sequenza (vedi useResetSelection)
  const handleResetToUsed = () => {
    if (!sourcesView) return
    setActionError(null)
    resetMutation.mutate(sourcesView, {
      onError: (err) => setActionError(errorMessage(err)),
    })
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
        setActionError(null)
        restoreMutation.mutate(v.id, {
          onSuccess: (accepted) => restoreJob.start(accepted.job_id),
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
        {/* Menu in un portale: non resta tagliato dal pannello che scorre. */}
        <LinkMenuButton
          testId="plus-sources"
          icon={Plus}
          label="Aggiungi fonte"
          items={[
            { label: 'Parte di registrazione', icon: Mic, onSelect: () => audioInputRef.current?.click() },
            { label: 'Appunti', icon: FileText, onSelect: () => setNotesModalOpen(true) },
            { label: 'Materiali (PDF, slide, foto)', icon: Paperclip, onSelect: () => materialsInputRef.current?.click() },
          ]}
        />
        <input
          ref={audioInputRef}
          type="file"
          multiple
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

      {pendingAudios.length > 1 && (
        <div
          className="flex items-center justify-between gap-2 rounded-lg border bg-card p-2.5 text-meta"
          data-testid="pending-audios-bar"
        >
          <div className="flex items-center gap-2 min-w-0">
            <Mic className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate font-medium">
              {pendingAudios.length} parti · {formatBytes(pendingAudios.reduce((sum, f) => sum + f.size, 0))}
            </span>
            <Button
              type="button"
              variant={unisciAudio ? 'default' : 'outline'}
              size="sm"
              className="h-7 px-2.5 text-xs"
              aria-pressed={unisciAudio}
              disabled={uploadingAudio}
              onClick={() => setUnisciAudio((prev) => !prev)}
            >
              Unisci
            </Button>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <Button
              size="sm"
              className="h-7 px-2.5 text-xs"
              disabled={uploadingAudio}
              onClick={handleUploadPendingAudios}
            >
              {uploadingAudio ? 'Caricamento…' : 'Carica'}
            </Button>
            <IconButton
              icon={X}
              label="Annulla"
              disabled={uploadingAudio}
              onClick={() => setPendingAudios([])}
            />
          </div>
        </div>
      )}

      {actionError && <Alert tone="danger">{actionError}</Alert>}
      {restoreJob.error && <Alert tone="danger">{restoreJob.error}</Alert>}
      {restoreJob.running && (
        <p className="flex items-center gap-1.5 text-meta text-muted-foreground" role="status" data-testid="restore-progress">
          <RotateCw className="size-3.5 animate-spin" aria-hidden />
          Ripristino in corso{restoreJob.percent != null ? ` · ${restoreJob.percent}%` : ''}
          {restoreJob.message ? ` · ${restoreJob.message}` : ''}
        </p>
      )}

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
            disabled={resetMutation.isPending}
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
          // Con l'audio principale il server indica la prima parte audio: basta il confronto.
          const isPrimary = sourcesView?.principale === s.id
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
                  title={isAudio ? 'Principale: la registrazione' : 'Fonte principale'}
                  data-testid="star-primary"
                >
                  <Star className="size-3.5 fill-current" />
                </span>
              ) : !(isAudio && audioIsPrimary) ? (
                <button
                  type="button"
                  className="flex size-4 shrink-0 cursor-pointer items-center justify-center text-muted-foreground opacity-0 hover:text-amber-500 group-hover:opacity-100 group-focus-within:opacity-100"
                  aria-label={`Usa ${s.nome} come principale`}
                  data-testid={`star-choose-${s.id}`}
                  onClick={() => handleSelectPrimary(s)}
                >
                  <Star className="size-3.5" />
                </button>
              ) : (
                <span className="size-4 shrink-0" aria-hidden />
              )}

              {/* Nome ed eventuali parti */}
              <div className="flex flex-col min-w-0 flex-1">
                <span className="truncate font-medium">{s.nome}</span>
                {s.parti && s.parti.length > 0 && (
                  <div
                    className="mt-1 flex flex-col gap-0.5 text-meta text-muted-foreground"
                    data-testid={`source-parts-${s.id}`}
                  >
                    {s.parti.map((p, idx) => (
                      <div key={idx} className="flex items-center gap-1.5 text-xs">
                        <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-bold tabular-nums">
                          {idx + 1}
                        </span>
                        <span className="truncate">{p.nome}</span>
                        {p.durata && <span className="tabular-nums">· {p.durata}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>

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

            const names = v.fonti_aggiunte.map((id) => sources.find((s) => s.id === id)?.nome ?? id)
            const added = names.length ? ` · ${names.join(', ')}` : ''

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
                    disabled={restoreMutation.isPending || restoreJob.running}
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
      <Modal open={notesModalOpen} onClose={() => setNotesModalOpen(false)} title="Aggiungi appunti" testId="notes-dialog" className="w-[min(448px,calc(100vw-32px))]">
        <div className="mt-3 flex flex-col gap-3">
          <textarea
            rows={5}
            placeholder="Incolla o scrivi il testo degli appunti..."
            value={notesText}
            onChange={(e) => setNotesText(e.target.value)}
            className="w-full rounded-md border bg-background p-2.5 text-body focus-visible:outline-2 focus-visible:outline-ring"
            autoFocus
          />
          <div className="flex flex-wrap justify-end gap-2">
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
      </Modal>

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
