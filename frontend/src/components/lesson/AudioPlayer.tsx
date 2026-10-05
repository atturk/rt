import { Pause, Play } from 'lucide-react'
import { useEffect, useState, type CSSProperties } from 'react'

import { Tooltip } from '@/components/ui/tooltip'
import { formatTime, type TimedSection } from '@/lib/audio'
import { clampRate, formatSpeed, nextSpeed, SPEEDS } from '@/lib/playbackRate'
import { usePreference } from '@/lib/preferences'
import { cn } from '@/lib/utils'
import { useLessonAudio } from './audio'

const SPEED_HINT = `Velocità: ${SPEEDS.map(formatSpeed).join(' · ')}`

/**
 * Barra audio fissa in basso (design 4.2, schermata 02): play, tempo, barra, durata e il
 * pulsante della velocità a valori fissi (1× → 1,25× → 1,5× → 1,75× → 2× → 1×). Lo stato è quello
 * condiviso con il documento (AudioProvider): i timecode delle unità spostano questo audio.
 * Frecce sulla barra: ±5 secondi.
 */
// `sections` resta nell'interfaccia: i timecode delle unità li gestisce il documento.
export function AudioPlayer({ lessonId, inline = false, className }: {
  lessonId: number
  sections?: TimedSection[]
  /** Dentro la pagina (revisione) invece che fissa in basso. */
  inline?: boolean
  className?: string
}) {
  const { audioRef, currentTime, setCurrentTime, seek } = useLessonAudio()
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(NaN)
  const [savedSpeed, setSpeed] = usePreference('audio.rate', 1)
  const speed = clampRate(Number(savedSpeed))
  const [error, setError] = useState(false)
  const known = Number.isFinite(duration) && duration > 0
  const [hover, setHover] = useState(false)

  // Con il mouse sul riquadro, le frecce saltano di 5 secondi (non mentre si scrive nel testo).
  useEffect(() => {
    if (!hover) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft')) return
      const target = event.target as HTMLElement | null
      if (target?.isContentEditable || target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      const audio = audioRef.current
      if (!audio) return
      event.preventDefault()
      seek(audio.currentTime + (event.key === 'ArrowRight' ? 5 : -5), !audio.paused)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hover, audioRef, seek])

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

  return (
    <section
      aria-label="Audio della lezione"
      data-testid="audio-player"
      data-inline={inline || undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={cn(
        'flex items-center gap-3 rounded-lg border bg-card py-2 pl-2 pr-3',
        inline
          ? 'relative w-full'
          : [
              'fixed bottom-4 left-1/2 z-20 -translate-x-1/2 shadow-panel',
              'md:left-[calc(50%+var(--rail-width)/2)] md:max-w-[calc(100vw-88px)]',
              'max-md:bottom-[calc(76px+env(safe-area-inset-bottom))] max-md:w-[calc(100vw-24px)] max-md:gap-2 max-md:p-2',
            ],
        className,
      )}
    >
      <audio
        ref={audioRef}
        src={`/api/v1/lessons/${lessonId}/audio`}
        preload="metadata"
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onSeeked={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDuration(e.currentTarget.duration)
          e.currentTarget.playbackRate = speed
        }}
        onDurationChange={(e) => setDuration(e.currentTarget.duration)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => setError(true)}
      />
      <Tooltip content={playing ? 'Pausa' : 'Riproduci'} side="top" describe={false}>
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
      {error && <p role="alert" className="absolute -top-7 left-0 right-0 text-center text-meta text-danger">Il browser non riesce a riprodurre questo audio.</p>}
    </section>
  )
}
