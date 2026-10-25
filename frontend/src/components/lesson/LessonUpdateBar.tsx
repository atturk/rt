import { useRef, useState, type ReactNode } from 'react'
import { Check, Info, Plus, RotateCw, Star, Undo2, X } from 'lucide-react'
import { errorMessage } from '@/api/client'
import {
  useResetSelection,
  useSources,
  useSourcesJob,
  useUpdateLesson,
  useUndoUpdate,
  useSetPrimarySource,
} from '@/api/sources'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { useHoverExpand } from '@/lib/useHoverExpand'

export interface LessonUpdateBarProps {
  lessonId: number
  className?: string
}

export function LessonUpdateBar({ lessonId, className }: LessonUpdateBarProps) {
  const sourcesQuery = useSources(lessonId)
  const updateMutation = useUpdateLesson(lessonId)
  const undoMutation = useUndoUpdate(lessonId)
  const resetMutation = useResetSelection(lessonId)
  const primaryMutation = useSetPrimarySource(lessonId)
  const job = useSourcesJob(lessonId)

  // La × vale per un solo aggiornamento: uno nuovo (altro `il`) fa tornare la riga.
  const [dismissedAt, setDismissedAt] = useState<string | null>(null)
  // Aperto al passaggio del mouse o col clic (anche al tocco o da tastiera): mostra Estendi e Ricostruisci.
  const { open: splitOpen, setOpen: setSplitOpen, ref: expandRef } = useHoverExpand<HTMLDivElement>()
  const splitRef = useRef<HTMLDivElement>(null)
  const [confirmRebuildOpen, setConfirmRebuildOpen] = useState(false)
  const [confirmPrimary, setConfirmPrimary] = useState<{ open: boolean; audioId: string | null }>({
    open: false,
    audioId: null,
  })
  const [lastMode, setLastMode] = useState<'extend' | 'rebuild'>('extend')

  const data = sourcesQuery.data
  if (!data) return null

  const isRunning = updateMutation.isPending || undoMutation.isPending || job.running
  const runUpdate = (mode: 'extend' | 'rebuild') => {
    setLastMode(mode)
    setSplitOpen(false)
    updateMutation.mutate(mode, { onSuccess: (accepted) => job.start(accepted.job_id) })
  }

  const failure = [updateMutation, undoMutation, resetMutation, primaryMutation]
    .map((m) => (m.error ? errorMessage(m.error) : null))
    .find(Boolean) ?? job.error
  const withError = (bar: ReactNode) => (
    <>
      {failure && (
        <Alert tone="danger" className={cn('mb-2', className)}>
          {failure}
        </Alert>
      )}
      {bar}
    </>
  )

  // 1. Stato durante l'aggiornamento
  if (isRunning) {
    return (
      <div
        className={cn(
          'mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-body',
          className,
        )}
        data-testid="lesson-update-bar"
        data-state="run"
      >
        <div className="flex items-center gap-2 text-meta text-foreground">
          <RotateCw className="size-4 animate-spin text-muted-foreground" aria-hidden />
          <span>
            Aggiornamento in corso · {lastMode === 'rebuild' ? 'Ricostruisci' : 'Estendi'}
            {job.message ? ` · ${job.message}` : ''}
          </span>
        </div>
        <div
          className="h-1.5 w-36 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-label="Avanzamento dell'aggiornamento"
          aria-valuenow={job.percent ?? undefined}
          data-testid="bar-progress"
        >
          {job.percent != null ? (
            <div className="h-full rounded-full bg-primary" style={{ width: `${job.percent}%` }} />
          ) : (
            <div className="h-full w-2/3 animate-pulse rounded-full bg-primary" />
          )}
        </div>
      </div>
    )
  }

  // 2. Stato solo ricostruzione (ordine o principale cambiati)
  if (data.solo_ricostruzione) {
    return withError(
      <>
        <div
          className={cn(
            'mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-body',
            className,
          )}
          data-testid="lesson-update-bar"
          data-state="rebuild"
        >
          <div className="flex items-center gap-2 text-meta text-foreground">
            <Info className="size-4 shrink-0 text-amber-500" aria-hidden />
            <span>{data.fonti_tolte_usate?.length
              ? (data.fonti_tolte_usate.length === 1 ? 'Hai tolto una fonte già usata' : `Hai tolto ${data.fonti_tolte_usate.length} fonti già usate`)
              : 'Ordine delle registrazioni cambiato: la lezione va ricostruita'}</span>
          </div>
          <div className="flex items-center gap-1">
            <IconButton
              icon={Undo2}
              label="Rimetti com'era"
              disabled={resetMutation.isPending}
              onClick={() => resetMutation.mutate(data)}
              data-testid="bar-reset-btn"
            />
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2.5 text-meta"
              onClick={() => setConfirmRebuildOpen(true)}
              data-testid="bar-solo-rebuild-btn"
            >
              <RotateCw className="size-3.5" />
              Ricostruisci
            </Button>
          </div>
        </div>

        <ConfirmDialog
          open={confirmRebuildOpen}
          title="Ricostruire la lezione?"
          confirmLabel="Ricostruisci"
          onCancel={() => setConfirmRebuildOpen(false)}
          onConfirm={() => {
            setConfirmRebuildOpen(false)
            runUpdate('rebuild')
          }}
        >
          <p>
            La lezione dovrà essere ricostruita: la scaletta si rifà da zero. Finché non premi
            Ricostruisci puoi tornare indietro, e se rimetti tutto com'era la riga sparisce. Lo
            studio resta, segnato come precedente dove l'unità cambia.
          </p>
        </ConfirmDialog>
      </>,
    )
  }

  // 3. Stato fonti nuove non ancora usate
  if (data.has_unused_sources) {
    const unusedList = data.sources.filter((s) => !s.usata)
    const unusedNames = unusedList.map((s) => s.nome).join(', ')

    const hasAudio = data.sources.some((s) => s.tipo === 'audio')
    const primarySource = data.sources.find((s) => s.id === data.principale)
    const audioNotPrimary = hasAudio && primarySource && primarySource.tipo !== 'audio'
    const firstAudio = data.sources.find((s) => s.tipo === 'audio')

    return withError(
      <>
        <div
          className={cn(
            'mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-body',
            className,
          )}
          data-testid="lesson-update-bar"
          data-state="new"
        >
          <div className="flex flex-wrap items-center gap-2 text-meta text-foreground min-w-0">
            <Info className="size-4 shrink-0 text-amber-500" aria-hidden />
            <span className="truncate">
              Fonti nuove non ancora usate{unusedNames ? `: ${unusedNames}` : ''}
            </span>
            {audioNotPrimary && firstAudio && (
              <button
                type="button"
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline ml-1"
                onClick={() => setConfirmPrimary({ open: true, audioId: firstAudio.id })}
                data-testid="bar-set-audio-primary-btn"
              >
                <Star className="size-3" />
                Rendi principale l'audio
              </button>
            )}
          </div>

          {/* Al passaggio del mouse Aggiorna si divide; al tocco o con la tastiera lo divide il clic,
              che quindi non avvia mai Estendi da solo. */}
          <div ref={expandRef} className="relative flex items-center gap-0.5">
            <div className={cn('flex', splitOpen && 'hidden')}>
              <Button
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 px-2.5 text-meta"
                aria-expanded={splitOpen}
                disabled={isRunning}
                onClick={() => {
                  setSplitOpen(true)
                  requestAnimationFrame(() => splitRef.current?.querySelector('button')?.focus())
                }}
                data-testid="bar-update-main-btn"
              >
                <RotateCw className="size-3.5" />
                Aggiorna
              </Button>
            </div>
            <div
              ref={splitRef}
              className={cn('hidden items-center gap-0.5', splitOpen && 'flex')}
              data-testid="bar-split"
            >
              <IconButton
                icon={Plus}
                label="Estendi: aggiunge unità, non tocca quelle esistenti"
                className="size-7"
                disabled={isRunning}
                onClick={() => runUpdate('extend')}
                data-testid="bar-extend-btn"
              />
              <IconButton
                icon={RotateCw}
                label="Ricostruisci: rifà la scaletta da zero"
                className="size-7"
                disabled={isRunning}
                onClick={() => setConfirmRebuildOpen(true)}
                data-testid="bar-rebuild-btn"
              />
            </div>
          </div>
        </div>

        <ConfirmDialog
          open={confirmRebuildOpen}
          title="Ricostruire la lezione?"
          confirmLabel="Ricostruisci"
          onCancel={() => setConfirmRebuildOpen(false)}
          onConfirm={() => {
            setConfirmRebuildOpen(false)
            runUpdate('rebuild')
          }}
        >
          <p>
            La scaletta si rifà da zero. Le unità cambiate perdono decisioni e stato di studio. Lo
            studio resta, segnato come precedente dove l'unità cambia.
          </p>
        </ConfirmDialog>

        <ConfirmDialog
          open={confirmPrimary.open}
          title="Usare la registrazione come fonte principale?"
          confirmLabel="Usa come principale"
          onCancel={() => setConfirmPrimary({ open: false, audioId: null })}
          onConfirm={() => {
            if (confirmPrimary.audioId) {
              primaryMutation.mutate(confirmPrimary.audioId)
            }
            setConfirmPrimary({ open: false, audioId: null })
          }}
        >
          <p>
            La lezione dovrà essere ricostruita: la scaletta si rifà da zero. Finché non premi
            Ricostruisci puoi tornare indietro, e se rimetti tutto com'era la riga sparisce. Lo
            studio resta, segnato come precedente dove l'unità cambia.
          </p>
        </ConfirmDialog>
      </>,
    )
  }

  // 4. Stato lezione appena aggiornata (con possibilità di annullamento)
  const u = data.ultimo_aggiornamento
  if (u && data.can_undo && dismissedAt !== u.il) {
    const nuoveStr = `${u.unita_nuove} ${u.unita_nuove === 1 ? 'unità nuova' : 'unità nuove'}`
    const cambiateStr = `${u.unita_cambiate} ${u.unita_cambiate === 1 ? 'cambiata' : 'cambiate'}`

    return withError(
      <div
        className={cn(
          'mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-body',
          className,
        )}
        data-testid="lesson-update-bar"
        data-state="done"
      >
        <div className="flex items-center gap-2 text-meta text-foreground">
          <Check className="size-4 text-primary" aria-hidden />
          <span>
            Lezione aggiornata · {nuoveStr}, {cambiateStr}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <IconButton
            icon={Undo2}
            label="Annulla aggiornamento"
            disabled={undoMutation.isPending}
            onClick={() => undoMutation.mutate()}
            data-testid="bar-undo-btn"
          />
          <IconButton
            icon={X}
            label="Chiudi"
            onClick={() => setDismissedAt(u.il)}
            data-testid="bar-close-btn"
          />
        </div>
      </div>,
    )
  }

  return withError(null)
}
