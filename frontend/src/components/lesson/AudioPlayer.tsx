import { Pause, Play, Rewind, FastForward, SkipBack, SkipForward } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useWaveform } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { formatTime, neighbourStart, type TimedSection } from '@/lib/audio'
import { clampRate, formatRate, loadRate, RATE_MAX, RATE_MIN, RATE_STEP, saveRate } from '@/lib/playbackRate'
import { useLessonAudio } from './audio'

function drawWaveform(canvas: HTMLCanvasElement, peaks: number[], progress: number) {
  const width = Math.max(1, canvas.clientWidth)
  const height = canvas.clientHeight || 64
  const ratio = window.devicePixelRatio || 1
  canvas.width = Math.round(width * ratio)
  canvas.height = Math.round(height * ratio)
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.scale(ratio, ratio)
  const styles = getComputedStyle(canvas)
  const played = styles.getPropertyValue('--wave-played').trim() || '#e98a16'
  const rest = styles.getPropertyValue('--wave-rest').trim() || '#8996aa'
  const data = peaks.length ? peaks : Array.from({ length: 160 }, (_, i) => 8 + 7 * Math.abs(Math.sin(i * 1.7)))
  const spacing = width / data.length
  const bar = Math.max(1, Math.min(3, spacing * 0.55))
  data.forEach((value, i) => {
    const h = Math.max(3, (value * (height - 6)) / 72)
    ctx.fillStyle = i / data.length <= progress ? played : rest
    ctx.fillRect(i * spacing, (height - h) / 2, bar, h)
  })
}

/** Valore della velocità che apre uno slider (0.5×–3×); si chiude con Esc o con un clic fuori. */
function SpeedControl({ rate, onChange }: { rate: number; onChange: (rate: number) => void }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.document.addEventListener('pointerdown', onPointer)
    return () => window.document.removeEventListener('pointerdown', onPointer)
  }, [open])

  return (
    <div ref={rootRef} className="relative w-14">
      <Button
        ref={buttonRef}
        variant="ghost"
        size="sm"
        className="w-14 tabular-nums"
        aria-label={`Velocità di riproduzione: ${formatRate(rate)}`}
        aria-expanded={open}
        aria-controls="rt-speed-popover"
        onClick={() => setOpen((v) => !v)}
      >
        {formatRate(rate)}
      </Button>
      {open && (
        <div
          id="rt-speed-popover"
          className="absolute bottom-full left-0 z-20 mb-2 flex w-64 items-center gap-3 rounded-lg border bg-card px-3 py-2 shadow-md"
          data-testid="speed-popover"
          onKeyDown={(e) => {
            if (e.key !== 'Escape') return
            e.preventDefault()
            e.stopPropagation()
            setOpen(false)
            buttonRef.current?.focus()
          }}
        >
          <label htmlFor="rt-speed" className="sr-only">
            Velocità di riproduzione
          </label>
          <input
            id="rt-speed"
            type="range"
            autoFocus
            min={RATE_MIN}
            max={RATE_MAX}
            step={RATE_STEP}
            value={rate}
            aria-valuetext={formatRate(rate)}
            className="min-w-0 flex-1 accent-primary"
            onChange={(e) => onChange(clampRate(Number(e.currentTarget.value)))}
          />
          <output htmlFor="rt-speed" className="w-12 text-right text-sm tabular-nums" data-testid="speed-value">
            {formatRate(rate)}
          </output>
        </div>
      )}
    </div>
  )
}

/** Player dell'audio della lezione (sostituisce rt/web/player.js). */
export function AudioPlayer({ lessonId, sections }: { lessonId: number; sections: TimedSection[] }) {
  const { audioRef, currentTime, setCurrentTime, seek } = useLessonAudio()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const waveform = useWaveform(lessonId, true)
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(NaN)
  const [speed, setSpeed] = useState(loadRate)
  const [error, setError] = useState(false)
  const progress = Number.isFinite(duration) && duration > 0 ? currentTime / duration : 0
  const peaks = useMemo(() => waveform.data?.peaks ?? [], [waveform.data])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    drawWaveform(canvas, peaks, progress)
    const observer = new ResizeObserver(() => drawWaveform(canvas, peaks, progress))
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [peaks, progress])

  // La velocità vale anche dopo un nuovo caricamento dell'audio (defaultPlaybackRate).
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    el.defaultPlaybackRate = speed
    el.playbackRate = speed
  }, [audioRef, speed])
  const changeSpeed = (rate: number) => {
    setSpeed(rate)
    saveRate(rate)
  }

  const audio = audioRef.current
  const toggle = () => {
    if (!audio) return
    if (audio.paused) audio.play().catch(() => setError(true))
    else audio.pause()
  }
  const jump = (direction: -1 | 1) => {
    const target = neighbourStart(sections, currentTime, direction)
    if (target != null) seek(target)
  }

  return (
    <section aria-label="Audio della lezione" className="rounded-xl border bg-card px-4 py-3" data-testid="audio-player">
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
      <canvas
        ref={canvasRef}
        className="block h-16 w-full cursor-pointer [--wave-played:#e98a16] [--wave-rest:#9aa3b2] dark:[--wave-rest:#5b6270]"
        role="slider"
        tabIndex={0}
        aria-label="Posizione nell'audio"
        aria-valuemin={0}
        aria-valuemax={Number.isFinite(duration) ? Math.round(duration) : 0}
        aria-valuenow={Math.round(currentTime)}
        aria-valuetext={formatTime(currentTime)}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          if (Number.isFinite(duration)) seek(((e.clientX - rect.left) / rect.width) * duration, !audio?.paused)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') seek(currentTime + 5, !audio?.paused)
          if (e.key === 'ArrowLeft') seek(currentTime - 5, !audio?.paused)
        }}
      />
      <div className="mt-1 flex justify-between text-xs tabular-nums text-muted-foreground">
        <span data-testid="audio-current">{formatTime(currentTime)}</span>
        <span>{formatTime(duration)}</span>
      </div>
      <div className="mt-2 flex items-center gap-1">
        <SpeedControl rate={speed} onChange={changeSpeed} />
        <div className="mx-auto flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Unità precedente" title="Unità precedente" onClick={() => jump(-1)}>
            <SkipBack />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Indietro di 15 secondi" onClick={() => seek(currentTime - 15, !audio?.paused)}>
            <Rewind />
          </Button>
          <Button variant="outline" size="icon" className="size-11 rounded-full" aria-label={playing ? 'Pausa' : 'Riproduci'} onClick={toggle}>
            {playing ? <Pause /> : <Play />}
          </Button>
          <Button variant="ghost" size="icon" aria-label="Avanti di 15 secondi" onClick={() => seek(currentTime + 15, !audio?.paused)}>
            <FastForward />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Unità successiva" title="Unità successiva" onClick={() => jump(1)}>
            <SkipForward />
          </Button>
        </div>
        <span className="w-14" />
      </div>
      {error && <p className="mt-1 text-xs text-danger">Il browser non riesce a riprodurre questo audio.</p>}
    </section>
  )
}
