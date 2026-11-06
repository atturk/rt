import { Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties } from 'react'

import { Tooltip } from '@/components/ui/tooltip'
import { pageArrowAllowed } from '@/lib/lessonNavigationKeys'
import { formatTime, type TimedSection } from '@/lib/audio'
import { clampRate, formatSpeed, nextSpeed, SPEEDS } from '@/lib/playbackRate'
import { usePreference } from '@/lib/preferences'
import { useIsPhone } from '@/lib/phone'
import { cn } from '@/lib/utils'
import {
  type AudioPlayerPosition,
  getAudioPosition,
  setAudioPosition,
  isLateralAllowed,
} from '@/lib/audioPosition'
import { useLessonAudio } from './audio'

const SPEED_HINT = `Velocità: ${SPEEDS.map(formatSpeed).join(' · ')}`

/**
 * Barra audio fissa in basso (design 4.2, schermata 02): play, tempo, barra, durata e il
 * pulsante della velocità a valori fissi (1× → 1,25× → 1,5× → 1,75× → 2× → 1×). Lo stato è quello
 * condiviso con il documento (AudioProvider): i timecode delle unità spostano questo audio.
 * Frecce sulla barra: ±5 secondi.
 */
// `sections` resta nell'interfaccia: i timecode delle unità li gestisce il documento.
export function AudioPlayer({ lessonId, inline = false, panelOpen = false, className, initialTime }: {
  lessonId: number
  sections?: TimedSection[]
  /** Dentro la pagina (revisione) invece che fissa in basso. */
  inline?: boolean
  /** Pannello laterale aperto: da md in su la barra resta centrata nella colonna del testo, non sotto il pannello. */
  panelOpen?: boolean
  className?: string
  /** Posizione iniziale all'apertura se non già in riproduzione. */
  initialTime?: number
}) {
  const { audioRef, currentTime, setCurrentTime, seek } = useLessonAudio()
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(NaN)
  const [savedSpeed, setSpeed] = usePreference('audio.rate', 1)
  const speed = clampRate(Number(savedSpeed))
  const [error, setError] = useState(false)
  const retry = useRef<{ lessonId: number; time: number; play: boolean } | null>(null)
  const [source, setSource] = useState({ lessonId, suffix: '' })
  const recovery = useRef(false)
  const known = Number.isFinite(duration) && duration > 0
  const [hover, setHover] = useState(false)

  const appliedInitialTime = useRef(false)
  useEffect(() => {
    if (appliedInitialTime.current) return
    if (initialTime == null || !Number.isFinite(initialTime)) return
    const el = audioRef.current
    if (!el) return
    if (!el.paused) {
      appliedInitialTime.current = true
      return
    }
    try {
      el.currentTime = initialTime
    } catch {
      // ignore
    }
    setCurrentTime(initialTime)
    seek(initialTime, false)
    appliedInitialTime.current = true
  }, [initialTime, audioRef, setCurrentTime, seek])

  const isPhone = useIsPhone()
  const [position, setPositionState] = useState<AudioPlayerPosition>(getAudioPosition)
  const [windowWidth, setWindowWidth] = useState(() => (typeof window !== 'undefined' ? window.innerWidth : 1200))

  useEffect(() => {
    const onResize = () => setWindowWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const lateralAllowed = !inline && isLateralAllowed(isPhone) && windowWidth >= 900
  const effectivePosition: AudioPlayerPosition = inline || !lateralAllowed ? 'bottom' : position

  const savePosition = (newPos: AudioPlayerPosition) => {
    setAudioPosition(newPos)
    setPositionState(newPos)
  }

  const [dragging, setDragging] = useState(false)
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [closestDock, setClosestDock] = useState<AudioPlayerPosition>('bottom')
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)

  const handlePointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (inline) return
    const target = e.target as HTMLElement | null
    if (target?.closest('button, input, select, textarea, a, [role="button"], [role="slider"]')) {
      return
    }
    dragStartRef.current = { x: e.clientX, y: e.clientY }
    setDragOffset({ x: 0, y: 0 })
    setDragging(true)
    setClosestDock(effectivePosition)
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      // jsdom might not support setPointerCapture
    }
  }

  const handlePointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (!dragStartRef.current) return
    const dx = e.clientX - dragStartRef.current.x
    const dy = e.clientY - dragStartRef.current.y
    setDragOffset({ x: dx, y: dy })

    const w = window.innerWidth || 1200
    const h = window.innerHeight || 800
    if (!lateralAllowed) {
      setClosestDock('bottom')
      return
    }
    const x = e.clientX
    const y = e.clientY
    const dBottom = Math.hypot(x - w / 2, y - (h - 40))
    const dLeft = Math.hypot(x - 40, y - h / 2)
    const dRight = Math.hypot(x - (w - 40), y - h / 2)

    if (dLeft < dBottom && dLeft < dRight) {
      setClosestDock('left')
    } else if (dRight < dBottom && dRight < dLeft) {
      setClosestDock('right')
    } else {
      setClosestDock('bottom')
    }
  }

  const handlePointerUp = (e: React.PointerEvent<HTMLElement>) => {
    if (!dragStartRef.current) return
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // ignore
    }
    const finalPos = lateralAllowed ? closestDock : 'bottom'
    savePosition(finalPos)
    setDragging(false)
    setDragOffset({ x: 0, y: 0 })
    dragStartRef.current = null
  }

  const handlePointerCancel = (e: React.PointerEvent<HTMLElement>) => {
    if (!dragStartRef.current) return
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // ignore
    }
    setDragging(false)
    setDragOffset({ x: 0, y: 0 })
    dragStartRef.current = null
  }

  // Sul computer le frecce saltano di 5 secondi in tutta la pagina (non mentre si scrive nel testo o in un menu);
  // sui dispositivi senza mouse solo con il riquadro sotto il puntatore, come prima.
  const [pointer, setPointer] = useState(() => !!window.matchMedia?.('(hover: hover)').matches)
  useEffect(() => {
    const media = window.matchMedia?.('(hover: hover)')
    if (!media) return
    const change = () => setPointer(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => {
    if (!hover && !pointer) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft')) return
      const target = event.target as HTMLElement | null
      if (target?.isContentEditable || target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      if (!hover && !pageArrowAllowed(event)) return
      const audio = audioRef.current
      if (!audio) return
      event.preventDefault()
      seek(audio.currentTime + (event.key === 'ArrowRight' ? 5 : -5), !audio.paused)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hover, pointer, audioRef, seek])

  // La velocità vale anche dopo un nuovo caricamento dell'audio (defaultPlaybackRate).
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    el.defaultPlaybackRate = speed
    el.playbackRate = speed
  }, [audioRef, speed])

  // L'elemento si legge al momento del clic: al primo render audioRef.current è ancora null.
  const toggle = () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) audio.play().catch(() => setError(true))
    else audio.pause()
  }
  const cycleSpeed = () => {
    const next = nextSpeed(speed)
    setSpeed(next)
  }

  const dragStyle: CSSProperties | undefined = dragging
    ? effectivePosition === 'bottom'
      ? { transform: `translate(calc(-50% + ${dragOffset.x}px), ${dragOffset.y}px)`, transition: 'none' }
      : { transform: `translate(${dragOffset.x}px, calc(-50% + ${dragOffset.y}px))`, transition: 'none' }
    : undefined

  return (
    <>
      {dragging && (
        <>
          <div
            data-testid="audio-dock-bottom"
            data-active={closestDock === 'bottom' || undefined}
            className={cn(
              'fixed bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-lg border-2 border-dashed pointer-events-none transition-colors duration-150',
              'h-12 w-[420px] max-w-[calc(100vw-88px)]',
              closestDock === 'bottom' ? 'border-primary bg-primary/10' : 'border-muted-foreground/30 bg-muted/5'
            )}
          />
          {lateralAllowed && (
            <>
              <div
                data-testid="audio-dock-left"
                data-active={closestDock === 'left' || undefined}
                className={cn(
                  'fixed left-4 top-1/2 z-10 -translate-y-1/2 rounded-lg border-2 border-dashed pointer-events-none transition-colors duration-150',
                  'w-14 h-48',
                  closestDock === 'left' ? 'border-primary bg-primary/10' : 'border-muted-foreground/30 bg-muted/5'
                )}
              />
              <div
                data-testid="audio-dock-right"
                data-active={closestDock === 'right' || undefined}
                className={cn(
                  'fixed right-4 top-1/2 z-10 -translate-y-1/2 rounded-lg border-2 border-dashed pointer-events-none transition-colors duration-150',
                  'w-14 h-48',
                  closestDock === 'right' ? 'border-primary bg-primary/10' : 'border-muted-foreground/30 bg-muted/5'
                )}
              />
            </>
          )}
        </>
      )}
      <section
        aria-label="Audio della lezione"
        data-testid="audio-player"
        data-inline={inline || undefined}
        data-position={effectivePosition}
        data-dragging={dragging || undefined}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={dragStyle}
        className={cn(
          'rounded-lg border bg-card shadow-panel',
          !inline && 'cursor-grab active:cursor-grabbing select-none transition-all duration-200 ease-out',
          inline
            ? 'relative flex items-center gap-3 w-full py-2 pl-2 pr-3'
            : effectivePosition === 'bottom'
              ? [
                  'fixed bottom-4 left-1/2 z-20 -translate-x-1/2 flex items-center gap-3 py-2 pl-2 pr-3',
                  'md:left-[calc(50%+var(--rail-width)/2)] md:max-w-[calc(100vw-88px)]',
                  panelOpen && 'md:left-[calc(50%+var(--rail-width)/2-var(--rt-panel-width)/2)] md:max-w-[calc(100vw-var(--rail-width)-var(--rt-panel-width)-32px)]',
                  'max-md:bottom-[calc(76px+env(safe-area-inset-bottom))] max-md:w-[calc(100vw-24px)] max-md:gap-2 max-md:p-2',
                ]
              : [
                  'fixed top-1/2 z-20 -translate-y-1/2 flex flex-col items-center gap-2 p-2 w-auto',
                  effectivePosition === 'left' ? 'left-4' : 'right-4',
                ],
          className,
        )}
      >
        <audio
          ref={audioRef}
          src={`/api/v1/lessons/${lessonId}/audio${source.lessonId === lessonId ? source.suffix : ''}`}
          preload="metadata"
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onSeeked={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => {
            setDuration(e.currentTarget.duration)
            e.currentTarget.playbackRate = speed
            if (recovery.current && retry.current?.lessonId === lessonId) {
              recovery.current = false
              e.currentTarget.currentTime = retry.current.time
              if (retry.current.play) e.currentTarget.play().catch(() => setError(true))
            }
          }}
          onDurationChange={(e) => setDuration(e.currentTarget.duration)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onError={(e) => {
            if (retry.current?.lessonId === lessonId) {
              setError(true)
              return
            }
            const audio = e.currentTarget
            retry.current = { lessonId, time: audio.currentTime, play: playing || !audio.paused }
            recovery.current = true
            setError(false)
            setSource({ lessonId, suffix: `?r=${Date.now()}` })
          }}
        />
        <Tooltip content={playing ? 'Pausa' : 'Riproduci'} side={effectivePosition === 'left' ? 'right' : 'top'} describe={false}>
          {(trigger) => (
            <button
              type="button"
              aria-label={playing ? 'Pausa' : 'Riproduci'}
              className="inline-flex size-(--control-size) shrink-0 items-center justify-center rounded-md bg-foreground text-background hover:shadow-[inset_0_0_0_1px_var(--bg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&_svg]:size-[18px] [&_svg]:stroke-[1.7]"
              onClick={toggle}
              {...trigger}
            >
              {playing ? <Pause aria-hidden /> : <Play aria-hidden />}
            </button>
          )}
        </Tooltip>
        {effectivePosition === 'bottom' || inline ? (
          <>
            <span className="font-mono text-meta tabular-nums max-md:text-[11px]" data-testid="audio-current">{formatTime(currentTime)}</span>
            <input
              type="range"
              aria-label="Posizione nell'audio"
              min={0}
              max={known ? Math.round(duration) : 0}
              step={1}
              value={Math.min(Math.round(currentTime), known ? Math.round(duration) : 0)}
              aria-valuetext={`${formatTime(currentTime)} di ${formatTime(duration)}`}
              disabled={!known}
              onChange={(e) => seek(Number(e.currentTarget.value), !audioRef.current?.paused)}
              onKeyDown={(e) => {
                // ±5 secondi, come la forma d'onda di prima (il passo nativo sarebbe 1 secondo).
                if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
                e.preventDefault()
                seek(currentTime + (e.key === 'ArrowRight' ? 5 : -5), !audioRef.current?.paused)
              }}
              className={cn('rt-seek h-1 min-w-4 cursor-pointer', inline ? 'flex-1' : 'w-[220px] max-md:w-auto max-md:flex-1')}
              style={{ '--seek': `${known ? (Math.min(currentTime, duration) / duration) * 100 : 0}%` } as CSSProperties}
            />
            <span className="font-mono text-meta tabular-nums text-muted-foreground max-md:text-[11px]">{formatTime(duration)}</span>
            <Tooltip content={SPEED_HINT} side="top" describe>
              {(trigger) => (
                <button
                  type="button"
                  aria-label={`Velocità di riproduzione: ${formatSpeed(speed)}`}
                  className="min-h-(--control-size) shrink-0 rounded-md border bg-card px-2 font-mono text-meta font-semibold tabular-nums hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  onClick={cycleSpeed}
                  data-testid="speed-button"
                  {...trigger}
                >
                  {formatSpeed(speed)}
                </button>
              )}
            </Tooltip>
          </>
        ) : (
          <>
            <span className="font-mono text-meta tabular-nums text-[11px]" data-testid="audio-current">{formatTime(currentTime)}</span>
            <div className="flex flex-col gap-1">
              <Tooltip content="Indietro di 5 secondi" side={effectivePosition === 'left' ? 'right' : 'top'}>
                {(trigger) => (
                  <button
                    type="button"
                    aria-label="Indietro di 5 secondi"
                    className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-card text-meta font-mono font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring text-[11px]"
                    onClick={() => seek(currentTime - 5, !audioRef.current?.paused)}
                    {...trigger}
                  >
                    −5s
                  </button>
                )}
              </Tooltip>
              <Tooltip content="Avanti di 5 secondi" side={effectivePosition === 'left' ? 'right' : 'top'}>
                {(trigger) => (
                  <button
                    type="button"
                    aria-label="Avanti di 5 secondi"
                    className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-card text-meta font-mono font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring text-[11px]"
                    onClick={() => seek(currentTime + 5, !audioRef.current?.paused)}
                    {...trigger}
                  >
                    +5s
                  </button>
                )}
              </Tooltip>
            </div>
            <Tooltip content={SPEED_HINT} side={effectivePosition === 'left' ? 'right' : 'top'} describe>
              {(trigger) => (
                <button
                  type="button"
                  aria-label={`Velocità di riproduzione: ${formatSpeed(speed)}`}
                  className="flex min-h-7 shrink-0 items-center justify-center rounded-md border bg-card px-1.5 font-mono text-[11px] font-semibold tabular-nums hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  onClick={cycleSpeed}
                  data-testid="speed-button"
                  {...trigger}
                >
                  {formatSpeed(speed)}
                </button>
              )}
            </Tooltip>
          </>
        )}
        {error && <p role="alert" className="absolute -top-7 left-0 right-0 text-center text-meta text-danger">Il browser non riesce a riprodurre questo audio.</p>}
      </section>
    </>
  )
}
