import { BookOpen, FileText, SlidersHorizontal, TextQuote, ChevronDown, Eraser, Gauge, Highlighter as HighlighterIcon, Info, List, Pause, Play, Sparkles, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { Link } from 'react-router'

import { detectSwipe, isElementScrollableX } from './swipe'

import { errorMessage } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import {
  recallKeys, useGenerateForUnits, useStudyLesson,
  type RecallType, type StudyUnit,
} from '@/api/recall'
import { useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '@/components/shell/PageHeader'
import { LightweightSession } from '@/components/recall/LightweightSession'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Chip } from '@/components/ui/chip'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { lessonTitle, type Lesson } from '@/lib/format'
import { formatDuration, longDate, subjectName } from '@/lib/lessonsPage'
import { withImageUrls } from '@/lib/images'
import { renderDelimitedMath } from '@/lib/math'
import { useIsPhone } from '@/lib/phone'
import { useHighlighterPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import { useZen } from '@/lib/zen'
import { cn } from '@/lib/utils'
import { HIGHLIGHT_COLORS, useStudyHighlighter, type HighlightMode } from './highlights'
import { SpeedReader } from './SpeedReader'
import { useStudyRead, useStudyStatus } from '@/api/studyProgress'
import { initialStudyUnit, nextStudyStatus, STATUS_LABELS, STUDY_ICONS, studyDate } from './studyProgress'
import { StudyStatusIcon } from './StudyStatusIcon'

/**
 * Studio (schermate 05, 05b, 06, wireframe Studio-Indice.dc.html):
 * si legge un'unità intera, poi le sue domande una alla volta, poi l'unità dopo;
 * l'indice "Unità N di M ▾" permette di saltare direttamente a qualsiasi unità.
 */
export function StudyFlow({ lessons, onlyUnits = null, back }: {
  /** Lezioni nell'ordine dello studio (pronte: rielaborazione valida). */
  lessons: Lesson[]
  /** Solo queste unità, partendo dalle domande (Domande su questa parte). */
  onlyUnits?: string[] | null
  back: { to: string; label: string }
}) {
  const [lessonIndex, setLessonIndex] = useState(0)
  const [unitIndex, setUnitIndex] = useState(0)
  const [phase, setPhase] = useState<'lettura' | 'domande'>(onlyUnits ? 'domande' : 'lettura')
  const [rereading, setRereading] = useState(false)
  const [indexOpen, setIndexOpen] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const closeGenerate = useCallback(() => setGenerateOpen(false), [])
  const [finished, setFinished] = useState(false)
  const lesson = lessons[lessonIndex] ?? null
  const study = useStudyLesson(lesson?.id ?? null)
  // Le unità della lezione nell'ordine: con onlyUnits quelle della parte.
  const [units, setUnits] = useState<StudyUnit[] | null>(null)
  const loaded = study.data && study.data.id === lesson?.id ? study.data : null
  useEffect(() => {
    // La lista si fissa all'ingresso nella lezione: dopo ogni risposta il conteggio cambia, l'ordine no.
    if (loaded && units === null) {
      // oxlint-disable-next-line react/set-state-in-effect
      setUnits(onlyUnits ? loaded.units.filter((u) => onlyUnits.includes(u.id)) : loaded.units)
      setUnitIndex(onlyUnits ? 0 : initialStudyUnit(loaded.units))
    }
  }, [loaded, units, onlyUnits])
  const unit = units?.[unitIndex] ?? null
  const live = loaded?.units.find((u) => u.id === unit?.id) ?? unit
  const liveUnits = units?.map(u => loaded?.units.find(current => current.id === u.id) ?? u) ?? []
  const status = useStudyStatus(lesson?.id ?? 0)
  const read = useStudyRead(lesson?.id ?? 0)
  const markRead = read.mutate
  const changeStatus = () => {
    if (unit && !status.isPending) status.mutate({ unitId: unit.id, status: nextStudyStatus(live?.status) })
  }

  useEffect(() => {
    if (!unit || finished || (phase !== 'lettura' && !rereading)) return
    const timer = window.setTimeout(() => markRead(unit.id), 3000)
    return () => window.clearTimeout(timer)
  }, [lesson?.id, unit?.id, phase, rereading, finished, markRead]) // oxlint-disable-line react-hooks/exhaustive-deps

  const goToUnit = (idx: number) => {
    setUnitIndex(idx)
    setPhase('lettura')
    setRereading(false)
    window.scrollTo?.({ top: 0 })
  }

  const advance = useCallback(() => {
    setRereading(false)
    if (units && unitIndex + 1 < units.length) {
      setUnitIndex(unitIndex + 1)
      setPhase(onlyUnits ? 'domande' : 'lettura')
    } else if (lessonIndex + 1 < lessons.length) {
      setLessonIndex(lessonIndex + 1)
      setUnitIndex(0)
      setUnits(null)
      setPhase('lettura')
    } else setFinished(true)
    window.scrollTo?.({ top: 0 })
  }, [units, unitIndex, lessonIndex, lessons.length, onlyUnits])

  const [detailsOpen, setDetailsOpen] = useState(false)
  const titleButtonRef = useRef<HTMLButtonElement>(null)
  const [highlighterPrefs, setHighlighterPrefs] = useHighlighterPrefs()
  const [hlMode, setHlMode] = useState<HighlightMode>('evidenzia')
  const [textRoot, setTextRoot] = useState<HTMLElement | null>(null)
  const [speedReading, setSpeedReading] = useState(false)
  const [readerMounted, setReaderMounted] = useState(false)
  const [readerContext, setReaderContext] = useState(false)
  const [readerSettings, setReaderSettings] = useState(false)
  const [tint, setTint] = useState<RsvpPreference['irlen']>(null)
  const settingsButton = useRef<HTMLDivElement>(null)
  const setZen = useZen()
  const closeReader = useCallback(() => { setSpeedReading(false); setReaderSettings(false); setIndexOpen(false) }, [])
  useEffect(() => {
    setZen({ active: speedReading, tint })
    return () => setZen({ active: false, tint: null })
  }, [speedReading, tint, setZen])
  useEffect(() => {
    if (speedReading || !readerMounted) return
    const timer = setTimeout(() => setReaderMounted(false), globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 300)
    return () => clearTimeout(timer)
  }, [speedReading, readerMounted])
  const highlights = useStudyHighlighter({
    root: phase === 'lettura' || rereading ? textRoot : null, lessonId: lesson?.id ?? 0, unitId: unit?.id ?? '',
    mode: hlMode, color: highlighterPrefs.color,
  })
  const arrows = highlighterPrefs.arrows

  // Tasti ← / → per cambiare unità nella sola fase di lettura (disattivabili da study.highlighter.arrows)
  useEffect(() => {
    if (phase !== 'lettura' || speedReading) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const isStatusKey = e.key.toLowerCase() === 's'
      if (!isStatusKey && (!arrows || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight'))) return
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable || target.tagName === 'SELECT')) {
        return
      }
      if (isStatusKey) {
        e.preventDefault()
        changeStatus()
      } else if (e.key === 'ArrowLeft') {
        if (unitIndex > 0) {
          e.preventDefault()
          goToUnit(unitIndex - 1)
        }
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        if (units && unitIndex + 1 < units.length) goToUnit(unitIndex + 1)
        else advance()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [phase, unitIndex, units, speedReading, arrows, live?.status, status.isPending]) // oxlint-disable-line react-hooks/exhaustive-deps

  // Gestione swipe touch fra le unità nella fase di lettura (F1)
  const swipeStartRef = useRef<{ x: number; y: number; time: number; id: number } | null>(null)

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (phase !== 'lettura' || rereading || speedReading || !arrows) return
    if (e.pointerType !== 'touch') return
    if (e.clientX <= 25) return
    if (window.getSelection()?.toString()) return
    if (isElementScrollableX(e.target as Element, e.currentTarget)) return

    swipeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      time: Date.now(),
      id: e.pointerId,
    }
  }

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!swipeStartRef.current || e.pointerId !== swipeStartRef.current.id) return
    const start = swipeStartRef.current
    swipeStartRef.current = null

    if (window.getSelection()?.toString()) return

    const swipe = detectSwipe({
      startX: start.x,
      startY: start.y,
      startTime: start.time,
      endX: e.clientX,
      endY: e.clientY,
      endTime: Date.now(),
    })

    if (swipe === 'next') {
      // Ultima unità: si passa alla lezione dopo (o alla schermata finale), come faceva
      // il pulsante "Unità successiva" che la b4 ha tolto.
      if (units && unitIndex + 1 < units.length) goToUnit(unitIndex + 1)
      else advance()
    } else if (swipe === 'prev') {
      if (unitIndex > 0) {
        goToUnit(unitIndex - 1)
      }
    }
  }

  const handlePointerCancel = () => {
    swipeStartRef.current = null
  }

  if (lessons.length === 0) {
    return (
      <StudyShell title="Studio" back={back}>
        <p className="text-body text-muted-foreground" data-testid="study-empty">Nessuna lezione pronta per lo Studio: serve la rielaborazione.</p>
      </StudyShell>
    )
  }
  const title = lesson ? lessonTitle(lesson) : 'Studio'
  if (finished) {
    return (
      <StudyShell title={title} back={back}>
        <div className="flex flex-col items-start gap-4" data-testid="study-done">
          <p className="text-body">{onlyUnits ? 'Hai finito le domande su questa parte.' : lessons.length > 1 ? 'Hai finito lo Studio di queste lezioni.' : 'Hai finito lo Studio della lezione.'}</p>
          <Link to={back.to} className="font-semibold text-link underline-offset-2 hover:underline">{back.label === 'Esci' ? 'Torna indietro' : back.label}</Link>
        </div>
      </StudyShell>
    )
  }
  if (study.isError) {
    return (
      <StudyShell title={title} back={back}>
        <p role="alert" className="flex items-center gap-3 text-body"><span className="text-danger">{errorMessage(study.error)}</span>
          <Button variant="outline" size="sm" onClick={() => void study.refetch()}>Riprova</Button></p>
      </StudyShell>
    )
  }
  if (!units || !loaded) {
    return (
      <StudyShell title={title} back={back}>
        <ReadingSkeleton />
      </StudyShell>
    )
  }
  const none = onlyUnits && units.every((u) => u.questions === 0)
  if (units.length === 0 || !unit || !live || none) {
    return (
      <StudyShell title={title} back={back}>
        {onlyUnits ? <NoQuestionsYet lessonId={lesson!.id} units={units.length ? units.map((u) => u.id) : onlyUnits} onReady={() => setUnits(null)} /> : (
          <div className="flex flex-col items-start gap-4">
            <p className="text-body text-muted-foreground">Questa lezione non ha unità da studiare.</p>
            {lessonIndex + 1 < lessons.length && <Button onClick={advance}>Lezione successiva</Button>}
          </div>
        )}
      </StudyShell>
    )
  }
  const audio = loaded.has_audio && live.start != null ? { lessonId: lesson!.id, start: live.start, end: live.end ?? null } : null
  const reading = phase === 'lettura' || rereading

  const lessonUrl = `/lezioni/${lesson!.id}#unit-${encodeURIComponent(unit.id)}`
  const titleButton = (
    <span className="inline-flex max-w-full items-center gap-1">
    <button
      ref={titleButtonRef}
      type="button"
      onClick={() => setDetailsOpen((v) => !v)}
      aria-haspopup="dialog"
      aria-expanded={detailsOpen}
      title="Dettagli della lezione"
      data-testid="study-title-button"
      className="inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring max-md:px-0"
    >
      <span className="truncate text-[15px] font-semibold text-foreground max-md:hidden">{title}</span>
      <Info className="size-4 shrink-0 text-muted-foreground max-md:size-[18px] max-md:text-foreground" aria-hidden />
      <span className="sr-only">Dettagli della lezione</span>
    </button>
    <IconLink label="Apri la lezione" icon={FileText} to={lessonUrl} />
    </span>
  )

  const headerActions = (
    <div className="flex items-center gap-1.5 max-md:gap-0" data-testid="study-header-tools">
      <HighlightTools
        mode={hlMode}
        color={highlighterPrefs.color}
        onMode={setHlMode}
        onColor={(color) => setHighlighterPrefs({ ...highlighterPrefs, color })}
        onClear={highlights.clear}
      />
      <span className="mx-0.5 h-4 w-px bg-border max-md:hidden" aria-hidden />
      <IconButton
        label={STATUS_LABELS[live.status ?? 'da-imparare']}
        aria-label={`Stato: ${STATUS_LABELS[live.status ?? 'da-imparare'].toLocaleLowerCase('it')}`}
        icon={STUDY_ICONS[live.status ?? 'da-imparare'].icon}
        className={STUDY_ICONS[live.status ?? 'da-imparare'].className}
        onClick={changeStatus}
        unavailable={status.isPending ? 'salvataggio in corso' : null}
        data-testid="study-status"
      />
      <IconButton
        label="Lettura veloce"
        icon={Gauge}
        onClick={() => {
          textRoot?.closest('[data-testid=study]')?.querySelector('audio')?.pause()
          window.scrollTo?.({ top: 0 })
          setSpeedReading(true)
          setReaderMounted(true)
          setIndexOpen(false)
          setDetailsOpen(false)
        }}
        unavailable={textRoot ? null : 'attendi il testo'}
        data-testid="study-rsvp-btn"
      />
      <UnitAudio key={`${lesson!.id}-${unit.id}`} clip={audio} />
      {units.length > 1 && (
        <UnitIndexMenu
          units={liveUnits}
          unitIndex={unitIndex}
          open={indexOpen}
          onOpenChange={setIndexOpen}
          onSelectUnit={goToUnit}
        />
      )}
    </div>
  )

  const zenActions = <div className="flex items-center gap-1">
    <IconButton label="Torna allo Studio" icon={BookOpen} onClick={closeReader} />
    <div ref={settingsButton}><IconButton label="Impostazioni della lettura veloce" icon={SlidersHorizontal} aria-expanded={readerSettings} active={readerSettings} onClick={() => setReaderSettings(!readerSettings)} /></div>
    <IconButton label="Contesto" icon={TextQuote} aria-pressed={readerContext} active={readerContext} onClick={() => setReaderContext(!readerContext)} />
    <UnitIndexMenu units={liveUnits} unitIndex={unitIndex} open={indexOpen} onOpenChange={setIndexOpen} onSelectUnit={goToUnit} />
  </div>

  return (
    <>
      {reading && (
        <StudyShell
          title={speedReading ? `${unit.id} ${unit.title}` : titleButton}
          back={speedReading ? undefined : back}
          actions={speedReading ? zenActions : headerActions}
          zen={speedReading}
          reader={readerMounted && textRoot && textRoot.dataset.unitId === unit.id ? <SpeedReader key={`${lesson!.id}-${unit.id}`} source={textRoot} active={speedReading} context={readerContext} settings={readerSettings} onSettingsChange={setReaderSettings} settingsButton={settingsButton} blocked={indexOpen} onTintChange={setTint} onClose={closeReader} /> : undefined}
          readingProps={{
            onPointerDown: handlePointerDown,
            onPointerUp: handlePointerUp,
            onPointerCancel: handlePointerCancel,
          }}
          popup={
            <>
              <GenerateUnitQuestions
                open={generateOpen}
                onClose={closeGenerate}
                lessonId={lesson!.id}
                unit={unit}
              />
              {lesson && (
              <LessonDetailsPopup
                lesson={lesson}
                unitCount={units.length}
                currentUnitIndex={unitIndex}
                lessonUrl={lessonUrl}
                open={detailsOpen}
                onClose={() => setDetailsOpen(false)}
                anchorRef={titleButtonRef}
              />
              )}
            </>
          }
          footer={
            rereading ? (
              <Button className="w-full max-w-(--reading-width) justify-center" onClick={() => setRereading(false)}>Torna alle domande</Button>
            ) : live.questions > 0 ? (
              <div className="flex w-full max-w-(--reading-width) items-center gap-2">
                <Button className="flex-1 justify-center" onClick={() => setPhase('domande')} data-testid="study-quiz">
                  Mettimi alla prova · {live.questions}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setGenerateOpen(true)}
                  aria-label="Genera altre domande"
                  data-testid="study-generate"
                  className="shrink-0"
                >
                  <Sparkles aria-hidden />
                  <span className="max-sm:hidden">Genera altre</span>
                </Button>
              </div>
            ) : (
              <Button className="w-full max-w-(--reading-width) justify-center" onClick={() => setGenerateOpen(true)} data-testid="study-generate">
                <Sparkles aria-hidden />
                Nessuna domanda · genera ora
              </Button>
            )
          }
        >
          {status.isError && <Alert tone="danger">{errorMessage(status.error)}</Alert>}
          {read.isError && <Alert tone="danger">{errorMessage(read.error)}</Alert>}
          <Dots units={liveUnits} current={unitIndex} onSelect={goToUnit} />
          <UnitText key={`${lesson!.id}-${unit.id}`} lessonId={lesson!.id} unit={live} highlightMode={hlMode} onReady={setTextRoot} />
        </StudyShell>
      )}
      {phase === 'domande' && (
        <div hidden={rereading}>
          {/* Ripasso dell'unità appena letta: la sessione di ripasso vera e propria, con
              "non lo so", voto, commento, chip per tipo e ritorno allo studio (4.2.2b3). */}
          <LightweightSession
            key={`${lesson!.id}-${unit.id}`}
            lessonId={lesson!.id}
            unit={{
              id: unit.id,
              title: unit.title,
              pending: (live.pending ?? {}) as Record<string, number>,
              onBack: () => setPhase('lettura'),
              onDone: advance,
              doneLabel: unitIndex + 1 < units.length ? 'Unità successiva' : lessonIndex + 1 < lessons.length ? 'Lezione successiva' : 'Fine',
            }}
          />
        </div>
      )}
    </>
  )
}

/** Popup con i dettagli della lezione aperto dal pulsante titolo. */
function LessonDetailsPopup({
  lesson,
  unitCount,
  currentUnitIndex,
  lessonUrl,
  open,
  onClose,
  anchorRef,
}: {
  lesson: Lesson
  unitCount: number
  currentUnitIndex: number
  lessonUrl: string
  open: boolean
  onClose: () => void
  anchorRef: React.RefObject<HTMLButtonElement | null>
}) {
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        !anchorRef.current?.contains(e.target as Node)
      ) {
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open, onClose, anchorRef])

  if (!open) return null

  const title = lessonTitle(lesson)
  const materia = lesson.materia ? subjectName(lesson.materia) : null
  const data = lesson.data ? longDate(lesson.data) : null
  const duration = lesson.duration_seconds ? formatDuration(lesson.duration_seconds) : null

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Dettagli della lezione"
      data-testid="study-details-popup"
      className="absolute left-14 top-[50px] z-30 grid w-[min(440px,calc(100%-24px))] gap-2.5 rounded-xl border bg-background p-4 text-body shadow-xl max-md:left-2 max-md:right-2 max-md:top-[54px] max-md:w-auto"
    >
      <strong className="font-semibold text-foreground [overflow-wrap:anywhere]">{title}</strong>
      <div className="grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-1 text-meta">
        {materia && (
          <>
            <span className="text-muted-foreground">Materia</span>
            <span>{materia}</span>
          </>
        )}
        {lesson.docente && (
          <>
            <span className="text-muted-foreground">Docente</span>
            <span>{lesson.docente}</span>
          </>
        )}
        {data && (
          <>
            <span className="text-muted-foreground">Data</span>
            <span>{data}</span>
          </>
        )}
        <span className="text-muted-foreground">Unità</span>
        <span>{unitCount} · stai leggendo la {currentUnitIndex + 1}</span>
        {duration && (
          <>
            <span className="text-muted-foreground">Audio</span>
            <span>{duration}</span>
          </>
        )}
      </div>
      <div>
        <Link
          to={lessonUrl}
          className="text-meta font-semibold text-link hover:underline"
          onClick={onClose}
        >
          Apri la lezione ›
        </Link>
      </div>
    </div>
  )
}

/** Intestazione (Esci, dove sei, azione a destra), colonna di lettura e pulsante in basso. */
function StudyShell({
  title,
  back,
  actions,
  popup,
  footer,
  readingProps,
  children,
  zen = false,
  reader,
}: {
  zen?: boolean
  reader?: ReactNode
  title: ReactNode
  back?: { to: string; label: string }
  actions?: ReactNode
  popup?: ReactNode
  footer?: ReactNode
  readingProps?: ComponentProps<'div'>
  children: ReactNode
}) {
  return (
    <div className="relative flex min-h-[calc(100dvh-64px)] flex-1 flex-col md:min-h-dvh" data-testid="study" data-zen={zen || undefined}>
      <PageHeader title={title} muted titleAs="h1" back={back} actions={actions} className="max-md:flex-nowrap max-md:gap-1 max-md:[--control-size:34px] [&_h1]:max-md:min-w-8 [&_h1]:max-md:text-meta" />
      {popup}
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div className="rt-study-text flex-1 touch-pan-y px-7 max-md:px-[18px]" aria-hidden={zen || undefined} inert={zen || undefined} {...readingProps}>
          <div className="mx-auto w-full max-w-(--reading-width) pb-8 pt-3" data-testid="study-reading-column">
            {children}
          </div>
        </div>
        {reader}
      </div>
      {footer && (
        <div aria-hidden={zen || undefined} inert={zen || undefined} className="rt-study-footer sticky bottom-0 z-10 flex justify-center border-t bg-background p-4 max-md:bottom-[calc(64px+env(safe-area-inset-bottom))] max-md:border-t-0 max-md:px-[18px] max-md:pt-0 [&_button]:min-h-12">
          {footer}
        </div>
      )}
    </div>
  )
}

function Dots({ units, current, onSelect }: { units: StudyUnit[]; current: number; onSelect: (index: number) => void }) {
  return (
    <div className="mb-6 mt-1 flex items-center gap-1" data-testid="study-dots">
      {units.map((u, i) => {
        const label = `${u.title}, ${STATUS_LABELS[u.status ?? 'da-imparare']}`
        return <button key={u.id} type="button" aria-label={`Unità ${i + 1}: ${label}`} title={label}
          onClick={() => onSelect(i)} aria-current={i === current ? 'step' : undefined}
          className="flex h-4 min-w-0 flex-1 cursor-pointer items-center rounded-md focus-visible:outline-2 focus-visible:outline-ring">
          <span data-status={u.status ?? 'da-imparare'} className={cn('w-full rounded-md',
            i === current ? 'h-[7px]' : 'h-[3px]',
            u.status === 'appreso' ? 'bg-success' : u.status === 'in-apprendimento' ? 'bg-warning' : u.status === 'ignorata' ? 'bg-danger' : 'bg-muted')} />
        </button>
      })}
    </div>
  )
}

function ReadingSkeleton() {
  return (
    <div aria-busy="true" aria-label="Carico l'unità" role="status">
      {[['40%', 18], ['100%', 10], ['92%', 10], ['75%', 10], ['100%', 10], ['60%', 10]].map(([width, height], i) => (
        <div key={i} className="my-3 rounded-md bg-muted" style={{ width: String(width), height: Number(height) }} />
      ))}
    </div>
  )
}

/** Testo dell'unità: HTML sanificato dall'API, immagini della lezione e formule. */
function UnitText({ lessonId, unit, highlightMode, onReady }: {
  lessonId: number
  unit: StudyUnit
  highlightMode: HighlightMode
  /** Il testo è pronto (formule disegnate): evidenziatore e lettura veloce lo usano. */
  onReady: (root: HTMLElement | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = ref.current
    if (!root) return
    let alive = true
    void renderDelimitedMath(root).finally(() => { if (alive) onReady(root) })
    return () => {
      alive = false
      onReady(null)
    }
  }, [unit.html, onReady])
  return (
    <section aria-labelledby="study-unit-title">
      <h2 id="study-unit-title" className="mb-3.5 text-heading font-semibold leading-snug">{unit.id} {unit.title}</h2>
      <div ref={ref} className="rt-document rt-reading" data-testid="study-text" data-unit-id={unit.id} data-hl-mode={highlightMode === 'gomma' ? 'erase' : undefined}
        dangerouslySetInnerHTML={{ __html: withImageUrls(unit.html, lessonId) }} />
    </section>
  )
}

/**
 * Audio della lezione per questa unità (dai timecode, non TTS): parte dall'inizio dell'unità e
 * si ferma alla fine. L'audio si scarica solo al primo ascolto.
 */
function UnitAudio({ clip }: { clip: { lessonId: number; start: number; end: number | null } | null }) {
  const ref = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState(false)
  if (!clip) return <IconButton label="Audio della lezione per questa unità" icon={Play} unavailable="audio non disponibile" />
  const toggle = () => {
    const audio = ref.current
    if (!audio) return
    if (!audio.paused) {
      audio.pause()
      return
    }
    const start = () => {
      if (audio.currentTime < clip.start || (clip.end != null && audio.currentTime >= clip.end - 0.25)) audio.currentTime = clip.start
      audio.play().catch(() => setError(true))
    }
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) start()
    else {
      audio.addEventListener('loadedmetadata', start, { once: true })
      audio.load()
    }
  }
  return (
    <>
      <audio
        ref={ref}
        src={`/api/v1/lessons/${clip.lessonId}/audio`}
        preload="none"
        data-testid="study-audio"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => setError(true)}
        onTimeUpdate={(e) => {
          if (clip.end != null && e.currentTarget.currentTime >= clip.end) e.currentTarget.pause()
        }}
      />
      <IconButton
        label={playing ? "Ferma l'audio dell'unità" : 'Audio della lezione per questa unità'}
        icon={playing ? Pause : Play}
        aria-pressed={playing}
        unavailable={error ? 'il browser non riesce a riprodurre questo audio' : null}
        onClick={toggle}
      />
    </>
  )
}

/** I tipi di domanda che si attaccano a una singola unità (le vaste no). */
const UNIT_TYPES: { id: RecallType; label: string }[] = [
  { id: 'quiz', label: 'Quiz' },
  { id: 'mirata', label: 'Mirata' },
  { id: 'caso', label: 'Caso clinico' },
  { id: 'esercizio', label: 'Esercizio' },
]

/** Domande su una parte che non ne ha ancora: si generano solo su quelle unità (quiz e mirate). */
function NoQuestionsYet({ lessonId, units, onReady }: { lessonId: number; units: string[]; onReady: () => void }) {
  const generate = useGenerateForUnits(lessonId)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const client = useQueryClient()
  const done = jobFinished(job.data)
  useEffect(() => {
    if (!done) return
    void client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }).then(onReady)
  }, [done, client, lessonId, onReady])
  return (
    <div className="flex flex-col items-start gap-4" data-testid="study-no-questions">
      <p className="text-body">Nessuna domanda su {units.length === 1 ? 'questa unità' : 'queste unità'} ({units.join(', ')}).</p>
      {jobId && !done ? (
        <p role="status" className="text-meta text-muted-foreground">Genero le domande…</p>
      ) : (
        <Button onClick={() => generate.mutate({ unitIds: units }, { onSuccess: (accepted) => setJobId(accepted.job_id) })} disabled={generate.isPending}>
          Genera le domande
        </Button>
      )}
      {job.data?.state === 'failed' && <Alert tone="danger">{job.data.error ?? 'Generazione non riuscita.'}</Alert>}
      {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
    </div>
  )
}

/** Popup "genera ora": tipo, quante e istruzioni, poi il job di recall sull'unità (4.2.2b3). */
function GenerateUnitQuestions({ open, onClose, lessonId, unit }: {
  open: boolean
  onClose: () => void
  lessonId: number
  unit: StudyUnit
}) {
  const generate = useGenerateForUnits(lessonId)
  const client = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const [qtype, setQtype] = useState<RecallType>('quiz')
  const [count, setCount] = useState('3')
  const [instructions, setInstructions] = useState('')
  const failed = job.data?.state === 'failed'
  const done = jobFinished(job.data)
  const running = jobId !== null && !done

  // Finito il job le domande ci sono: si aggiorna lo Studio e si chiude, senza partire
  // col ripasso (il pulsante "Mettimi alla prova" aspetta un clic).
  useEffect(() => {
    if (!done || failed) return
    void client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }).then(onClose)
  }, [done, failed, client, lessonId, onClose])

  return (
    <Modal open={open} onClose={running ? () => undefined : onClose} title={`Genera domande · ${unit.title}`} testId="study-generate-modal">
      <div className="mt-3 flex flex-col gap-3">
        <div>
          <span className="mb-1.5 block text-meta text-muted-foreground">Tipo</span>
          <div role="group" aria-label="Tipo di domanda" className="flex flex-wrap gap-1.5">
            {UNIT_TYPES.map(({ id, label }) => (
              <Chip key={id} size="sm" active={qtype === id} aria-pressed={qtype === id} disabled={running} onClick={() => setQtype(id)}>
                {label}
              </Chip>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="study-gen-count" className="text-meta text-muted-foreground">Quante</label>
          <Input
            id="study-gen-count"
            type="number"
            min="1"
            max="20"
            disabled={running}
            value={count}
            onChange={(e) => setCount(e.target.value)}
            className="h-8 w-16 px-2 py-0 text-center"
          />
        </div>
        <div>
          <label htmlFor="study-gen-instructions" className="mb-1 block text-meta text-muted-foreground">
            Istruzioni aggiuntive (facoltative)
          </label>
          <textarea
            id="study-gen-instructions"
            rows={2}
            disabled={running}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Per esempio: concentrati sui valori soglia"
            className="block w-full resize-none rounded-md border bg-card px-2.5 py-1.5 text-meta placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
          />
        </div>
        {failed && <Alert tone="danger">{job.data?.error ?? 'Generazione non riuscita.'}</Alert>}
        {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
        <div className="mt-1 flex items-center justify-end gap-2">
          {running ? (
            <p role="status" className="flex-1 text-meta text-muted-foreground">Genero le domande su {unit.id}…</p>
          ) : (
            <Button variant="outline" size="sm" onClick={onClose}>Annulla</Button>
          )}
          <Button
            size="sm"
            disabled={running || generate.isPending}
            data-testid="study-generate-start"
            onClick={() =>
              generate.mutate(
                { unitIds: [unit.id], qtype, count: Math.min(20, Math.max(1, parseInt(count, 10) || 3)), instructions },
                { onSuccess: (accepted) => setJobId(accepted.job_id) },
              )
            }
          >
            <Sparkles aria-hidden />
            {running ? 'Generazione…' : 'Genera'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/** Indice delle unità della lezione (wireframe Studio-Indice.dc.html e Telefono-Studio-Indice.dc.html). */
function UnitIndexMenu({
  units,
  unitIndex,
  open,
  onOpenChange,
  onSelectUnit,
}: {
  units: StudyUnit[]
  unitIndex: number
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectUnit: (index: number) => void
}) {
  const phone = useIsPhone()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    }
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpenChange(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open, onOpenChange])

  // Raggruppamento per prefisso di sezione (1., 2., ecc.)
  const sectionGroups: { key: string; title: string; items: { unit: StudyUnit; index: number }[] }[] = []
  units.forEach((u, i) => {
    const secKey = u.id.includes('.') ? u.id.split('.')[0] : ''
    let group = sectionGroups.find((g) => g.key === secKey)
    if (!group) {
      group = { key: secKey, title: secKey ? `Sezione ${secKey}` : '', items: [] }
      sectionGroups.push(group)
    }
    group.items.push({ unit: u, index: i })
  })

  const renderItems = () => (
    <div className="flex flex-col gap-1">
      {sectionGroups.map((g) => (
        <div key={g.key || 'root'}>
          {g.title && (
            <p className="px-2.5 pt-2 pb-1 text-meta font-semibold uppercase tracking-[.05em] text-muted-foreground">
              {g.title}
            </p>
          )}
          {g.items.map(({ unit: u, index: i }) => (
            <button
              key={u.id}
              type="button"
              role="menuitem"
              className={cn(
                'flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-body transition-colors hover:bg-muted',
                i === unitIndex && 'bg-accent font-medium text-accent-foreground',
              )}
              onClick={() => {
                onSelectUnit(i)
                onOpenChange(false)
              }}
            >
              <span className="mr-2"><StudyStatusIcon status={u.status} /></span>
              <span className="min-w-0 flex-1 truncate">{u.id} {u.title}</span>
              <span className="ml-2 shrink-0 text-meta text-muted-foreground">
                {i === unitIndex ? 'qui' : studyDate(u.status_at)}
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  )

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5 px-2.5 text-meta text-foreground"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        data-testid="unit-index-toggle"
      >
        <List className="size-3.5 shrink-0" aria-hidden />
        <span>{phone ? `${unitIndex + 1} di ${units.length}` : `Unità ${unitIndex + 1} di ${units.length}`}</span>
        {!phone && <ChevronDown className="size-3.5 shrink-0" aria-hidden />}
      </Button>

      {open && !phone && (
        <div
          role="menu"
          aria-label="Vai a un'unità"
          data-testid="unit-index-menu"
          className="absolute right-0 top-10 z-30 max-h-80 w-80 overflow-y-auto rounded-lg border bg-card p-1.5 shadow-panel"
        >
          {renderItems()}
        </div>
      )}

      {open && phone && (
        <div
          className="fixed inset-0 z-50 flex flex-col justify-end bg-black/40 backdrop-blur-[2px]"
          onClick={(e) => {
            if (e.target === e.currentTarget) onOpenChange(false)
          }}
        >
          <section
            aria-label="Vai a un'unità"
            data-testid="unit-index-sheet"
            className="flex max-h-[75vh] flex-col rounded-t-[14px] bg-card p-4 shadow-panel"
          >
            <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-border" />
            <div className="flex items-center justify-between pb-2">
              <h2 className="text-body font-semibold">Vai a un'unità</h2>
              <IconButton label="Chiudi" icon={X} onClick={() => onOpenChange(false)} />
            </div>
            <div className="flex-1 overflow-y-auto pt-1">
              {renderItems()}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

/**
 * Evidenziatore e gomma (4.2.2, H1): selettore a due posizioni come quello di Lezioni; un clic
 * sull'evidenziatore già attivo cambia colore, a giro. Il cestino toglie tutto, dopo una conferma.
 */
function HighlightTools({ mode, color, onMode, onColor, onClear }: {
  mode: HighlightMode
  color: number
  onMode: (mode: HighlightMode) => void
  onColor: (color: number) => void
  onClear: () => Promise<void>
}) {
  const [confirm, setConfirm] = useState(false)
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!confirm) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setConfirm(false) }
    const onClick = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setConfirm(false) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [confirm])
  const segment = 'relative inline-flex size-8 items-center justify-center rounded-md text-muted-foreground aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-sm'
  return (
    <div className="relative flex items-center gap-1" ref={ref}>
      <div role="group" aria-label="Evidenziatore" className="inline-flex rounded-lg bg-muted p-0.5" data-testid="highlight-tools">
        <button
          type="button"
          aria-pressed={mode === 'evidenzia'}
          aria-label={mode === 'evidenzia' ? `Evidenziatore ${HIGHLIGHT_COLORS[color]}: clic per cambiare colore` : 'Evidenziatore'}
          title={mode === 'evidenzia' ? `Evidenziatore ${HIGHLIGHT_COLORS[color]} (clic: colore successivo)` : 'Evidenziatore'}
          data-color={color}
          data-testid="highlight-pen"
          className={segment}
          onClick={() => (mode === 'evidenzia' ? onColor((color + 1) % HIGHLIGHT_COLORS.length) : onMode('evidenzia'))}
        >
          <HighlighterIcon className="size-4" aria-hidden />
          <span className={`absolute bottom-1 left-2 right-2 h-[3px] rounded-full rt-hl-${color}`} aria-hidden />
        </button>
        <button type="button" aria-pressed={mode === 'gomma'} aria-label="Gomma" title="Gomma: clic su un'evidenziazione per toglierla"
          data-testid="highlight-eraser" className={segment} onClick={() => onMode('gomma')}>
          <Eraser className="size-4" aria-hidden />
        </button>
      </div>
      <IconButton label="Togli tutte le evidenziazioni" icon={Trash2} aria-expanded={confirm} onClick={() => setConfirm(!confirm)} data-testid="highlight-clear" />
      {confirm && (
        <div role="dialog" aria-label="Togli le evidenziazioni" className="absolute right-0 top-10 z-30 w-64 rounded-lg border bg-card p-3 text-body shadow-panel">
          <p>Togli tutte le evidenziazioni di questa unità?</p>
          {failed && <p className="mt-1 text-meta text-danger">Non riuscito, riprova.</p>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setConfirm(false)}>Annulla</Button>
            <Button size="sm" variant="destructive" data-testid="highlight-clear-confirm"
              onClick={() => onClear().then(() => { setFailed(false); setConfirm(false) }, () => setFailed(true))}>Togli</Button>
          </div>
        </div>
      )}
    </div>
  )
}
