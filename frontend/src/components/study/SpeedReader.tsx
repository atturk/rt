import { Pause, Play, Rewind, RotateCcw, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'

import { useIsPhone } from '@/lib/phone'
import { useRsvpPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import { Checkbox } from '@/components/settings/common'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SlideToggle } from '@/components/ui/slide-toggle'
import { cn } from '@/lib/utils'
import {
  MAX_WPM, MIN_WPM, focusIndex, formatRemaining, isFullStop, nextSentence, previousSentence, readUnitWords,
  remainingSeconds, surrounding, wordDelay,
} from './rsvp'

const RING = 2 * Math.PI * 50
const NOISE_KINDS = [['bianco', 'Bianco'], ['rosa', 'Rosa'], ['marrone', 'Marrone']] as const
const TINTS = [['pesca', 'Pesca'], ['menta', 'Menta'], ['pergamena', 'Pergamena']] as const
const ORPS = [['prima', 'Prima'], ['bilanciata', 'Bilanciata'], ['dopo', 'Dopo']] as const
const STEPS = [1, 3, 5, 10]

/** Lettura veloce integrata nello Studio: conserva suoni, tasti e preferenze. */
export function SpeedReader({ source, active, context, settings, onSettingsChange, settingsButton, blocked, onTintChange, onClose }: {
  source: Element; active: boolean; context: boolean; settings: boolean; onSettingsChange: (open: boolean) => void
  settingsButton: RefObject<HTMLElement | null>; blocked: boolean
  onTintChange: (tint: RsvpPreference['irlen']) => void; onClose: () => void
}) {
  const [saved, save] = useRsvpPrefs()
  const [prefs, setPrefs] = useState<RsvpPreference>(saved)
  const { words, paragraphs } = useMemo(() => readUnitWords(source), [source])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  useEffect(() => onTintChange(prefs.irlen), [prefs.irlen, onTintChange])
  const phone = useIsPhone()
  const [sound] = useState(createSound)
  const prefsRef = useRef(prefs)
  const ramp = useRef(0)
  const persist = useRef<ReturnType<typeof setTimeout>>(undefined)
  useLayoutEffect(() => { prefsRef.current = prefs }, [prefs])

  /** Le preferenze si vedono subito e si salvano su RT poco dopo (gli slider cambiano spesso). */
  const update = useCallback((change: Partial<RsvpPreference>) => {
    setPrefs((old) => {
      const next = { ...old, ...change }
      clearTimeout(persist.current)
      persist.current = setTimeout(() => { persist.current = undefined; save(next) }, 400)
      return next
    })
  }, [save])
  const saveRef = useRef(save)
  useLayoutEffect(() => { saveRef.current = save }, [save])
  useEffect(() => () => {
    if (persist.current) { clearTimeout(persist.current); saveRef.current(prefsRef.current) }
  }, [])

  const previousSettings = useRef(settings)
  useLayoutEffect(() => {
    if (previousSettings.current && !settings && persist.current) {
      clearTimeout(persist.current)
      persist.current = undefined
      saveRef.current(prefsRef.current)
    }
    previousSettings.current = settings
  }, [settings])

  const word = words[index]?.text ?? ''
  const full = isFullStop(word, prefs.comma)

  useEffect(() => {
    if (!active || !playing || !words[index]) return
    const text = words[index].text
    const current = prefsRef.current
    const end = isFullStop(text, current.comma)
    if (current.sound) sound.click(end, current.pitch)
    const delay = wordDelay(text, current, ramp.current)
    if (ramp.current > 0) ramp.current--
    const timer = setTimeout(() => {
      if (index < words.length - 1) setIndex(index + 1)
      else setPlaying(false)
    }, delay)
    return () => clearTimeout(timer)
  }, [active, playing, index, words, sound])

  // Il rumore suona durante la lettura; in pausa solo l'anteprima di 2 s delle impostazioni.
  useEffect(() => {
    if (!active || !playing || !prefs.noise) return
    sound.noise(prefs.noise, prefsRef.current.noiseVolume)
    return () => sound.stopNoise()
  }, [active, playing, prefs.noise, sound])
  useEffect(() => sound.volume(prefs.noiseVolume), [prefs.noiseVolume, sound])
  useEffect(() => () => sound.dispose(), [sound])

  const play = useCallback(() => {
    if (!words.length) return
    sound.unlock()
    ramp.current = 5
    setIndex((i) => (i >= words.length - 1 ? 0 : i))
    setPlaying(true)
  }, [words.length, sound])
  const toggle = useCallback(() => (playing ? setPlaying(false) : play()), [playing, play])
  const jump = useCallback((to: number) => {
    setIndex(Math.max(0, Math.min(words.length - 1, to)))
    if (playing) ramp.current = 5
  }, [words.length, playing])

  useEffect(() => {
    if (!active || blocked) return
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return
      const field = e.target instanceof Element && e.target.closest('input, textarea, select, [contenteditable=true], header, [data-testid=speed-reader-settings]')
      if (field && e.key !== 'Escape') return
      const keys: Record<string, () => void> = {
        ' ': toggle,
        ArrowLeft: () => jump(previousSentence(words, index)),
        ArrowRight: () => jump(nextSentence(words, index)),
        ArrowUp: () => update({ wpm: Math.min(MAX_WPM, prefsRef.current.wpm + 25) }),
        ArrowDown: () => update({ wpm: Math.max(MIN_WPM, prefsRef.current.wpm - 25) }),
        Home: () => { setPlaying(false); setIndex(0) },
        Escape: () => {
          if (settings) { onSettingsChange(false); settingsButton.current?.querySelector('button')?.focus() }
          else onClose()
        },
      }
      const action = keys[e.key]
      if (!action) return
      // Spazio su un pulsante lo premerebbe due volte.
      e.preventDefault()
      e.stopPropagation()
      action()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, blocked, toggle, jump, update, words, index, settings, settingsButton, onSettingsChange, onClose])

  const closeSettings = () => { onSettingsChange(false); settingsButton.current?.querySelector('button')?.focus() }

  const around = surrounding(words, index)
  const k = word ? focusIndex(word, prefs.orp) : 0
  const remaining = remainingSeconds(words.length, index, prefs.wpm)
  const progress = words.length ? (index + 1) / words.length : 0
  const animate = playing && full && !matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const para = paragraphs[words[index]?.para ?? 0] ?? []

  return (
    <div
      role="region"
      aria-label="Lettura veloce"
      aria-hidden={!active || undefined}
      inert={!active || undefined}
      data-testid="speed-reader"
      data-active={active || undefined}
      data-settings={settings && !phone || undefined}
      className="rt-rsvp absolute inset-0 flex flex-col gap-3 overflow-hidden bg-background px-5 pb-[max(20px,env(safe-area-inset-bottom))] pt-5 text-foreground max-md:px-3.5"
    >
      <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-[18px]">
        {context && (
          <div data-testid="speed-reader-context" className="absolute left-1/2 top-0 z-[2] max-h-[45%] w-[min(680px,100%)] -translate-x-1/2 overflow-auto rounded-xl border border-border bg-card px-3.5 py-2.5 text-body leading-[1.7] text-muted-foreground">
            {para.map((piece, i) => (
              <span key={i} className={cn(piece.index !== null && piece.index < index && 'text-foreground',
                piece.index === index && 'font-semibold text-(--rsvp-focus)')} data-current={piece.index === index || undefined}>
                {piece.text}{' '}
              </span>
            ))}
          </div>
        )}
        <div className="min-h-[1.5em] max-w-[92%] text-center text-heading leading-normal text-muted-foreground max-md:text-body" data-testid="speed-reader-before">
          {playing ? '' : around.before}
        </div>
        <div
          key={animate ? `out-${index}` : 'still'}
          className={cn('rt-rsvp-word', prefs.dyslexic && 'dyslexic', animate && 'out')}
          style={{ '--rsvp-size': `${phone ? Math.round(prefs.size * 0.6) : prefs.size}px`, '--rsvp-out': `${Math.max(250, prefs.pauseMs + 60000 / prefs.wpm)}ms` } as CSSProperties}
          data-testid="speed-reader-word"
          data-kind={full ? 'fine' : 'normale'}
          aria-live="off"
        >
          <span className="pre">{word.slice(0, k)}</span><span className="orp">{word.charAt(k)}</span><span className="post">{word.slice(k + 1)}</span>
        </div>
        <div className="min-h-[1.5em] max-w-[92%] text-center text-heading leading-normal text-muted-foreground max-md:text-body" data-testid="speed-reader-after">
          {playing ? '' : around.after}
        </div>
        {!words.length && <p className="text-body text-muted-foreground">Questa unità non ha testo da leggere.</p>}
      </div>

      <div className="grid grid-cols-1 items-center justify-items-center gap-x-5 gap-y-1 text-meta text-muted-foreground">
        <span>Velocità <b className="font-normal text-foreground">{prefs.wpm}</b> parole/min</span>
        <input type="range" min={MIN_WPM} max={MAX_WPM} step={25} value={prefs.wpm} aria-label="Velocità" className="w-[220px] accent-accent-foreground justify-self-center"
          onChange={(e) => update({ wpm: Number(e.target.value) })} />
      </div>

      <div className="mt-1.5 flex items-center justify-center gap-[26px]">
        <RoundButton label={`Indietro di ${prefs.step} parole`} onClick={() => jump(index - prefs.step)} note={`−${prefs.step}`}>
          <Rewind className="size-5" fill="currentColor" aria-hidden />
        </RoundButton>
        <button type="button" onClick={toggle} aria-label={playing ? 'Pausa' : 'Avvia'} data-testid="speed-reader-play" autoFocus
          className="relative inline-flex size-[92px] items-center justify-center rounded-full border border-border bg-accent text-accent-foreground">
          <svg className="absolute -inset-1.5 size-[104px] -rotate-90" viewBox="0 0 104 104" aria-hidden>
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--border)" />
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--rsvp-focus)" strokeLinecap="round"
              strokeDasharray={RING} strokeDashoffset={RING * (1 - progress)} />
          </svg>
          {playing ? <Pause className="size-[26px]" fill="currentColor" aria-hidden /> : <Play className="size-[26px]" fill="currentColor" aria-hidden />}
        </button>
        <RoundButton label="Ricomincia l'unità" onClick={() => { setPlaying(false); setIndex(0) }}>
          <RotateCcw className="size-5" aria-hidden />
        </RoundButton>
      </div>
      <div className="mt-3 text-center text-meta text-muted-foreground" data-testid="speed-reader-count">
        {words.length ? `${index + 1} / ${words.length} parole · ${formatRemaining(remaining)}` : ''}
      </div>
      {settings && (
        <SettingsPanel anchor={settingsButton} phone={phone} prefs={prefs} update={update} onDone={closeSettings}
          onPreviewNoise={(kind, volume) => { if (!kind) sound.stopNoise(); else if (!playing) sound.preview(kind, volume) }} onPitch={(pitch) => sound.click(false, pitch)} />
      )}
    </div>
  )
}

function Pill(props: React.ComponentProps<typeof Button>) { return <Button variant="outline" size="sm" {...props} /> }

function RoundButton({ label, onClick, note, children }: { label: string; onClick: () => void; note?: string; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} onClick={onClick}
      className="relative inline-flex size-[58px] items-center justify-center rounded-full border border-border bg-muted text-foreground">
      {children}
      {note && <small className="absolute -bottom-[18px] text-meta text-muted-foreground">{note}</small>}
    </button>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (on: boolean) => void }) {
  return <Checkbox id={`rsvp-${label}`} label={label} checked={checked} onChange={onChange} />
}

function Segments<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: readonly (readonly [T, string])[]; onChange: (value: T) => void
}) {
  return <SlideToggle label={label} value={String(value)} options={options.map(([v, text]) => ({ value: String(v), label: text }))}
    onChange={next => { const choice = options.find(([v]) => String(v) === next); if (choice) onChange(choice[0]) }} />
}

function Row({ children }: { children: ReactNode }) {
  return <div className="grid gap-[7px] border-b border-border px-3.5 py-2.5 last:border-b-0">{children}</div>
}

function SettingsPanel({ anchor, phone, prefs, update, onDone, onPreviewNoise, onPitch }: {
  anchor: RefObject<HTMLElement | null>
  phone: boolean
  prefs: RsvpPreference
  update: (change: Partial<RsvpPreference>) => void
  onDone: () => void
  onPreviewNoise: (kind: RsvpPreference['noise'], volume: number) => void
  onPitch: (pitch: number) => void
}) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!phone) return
    const outside = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node) && !anchor.current?.contains(event.target as Node)) onDone()
    }
    window.addEventListener('mousedown', outside)
    return () => window.removeEventListener('mousedown', outside)
  }, [phone, anchor, onDone])
  const section = (title: string) => <h3 className="px-3.5 pb-1 pt-4 text-meta font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
  return (
    <section ref={ref} role="dialog" aria-label="Impostazioni della lettura veloce" data-testid="speed-reader-settings"
      className={cn('rt-rsvp-settings z-30 overflow-auto border bg-card py-1 text-body shadow-panel [&_input]:accent-accent-foreground',
        phone ? 'fixed inset-x-0 bottom-0 max-h-[75dvh] rounded-t-[14px] pb-[env(safe-area-inset-bottom)]' : 'absolute inset-y-0 right-0 w-[340px] border-y-0 border-r-0')}>
      <Row><div className="flex items-center justify-between"><b className="font-semibold">Impostazioni</b><IconButton label="Chiudi le impostazioni" icon={X} onClick={onDone} /></div></Row>
      {section('Lettura')}
      <Row>
        <span>Pausa dopo la frase <b className="font-normal">{prefs.pauseMs}</b> ms</span>
        <input type="range" min={0} max={1200} step={50} value={prefs.pauseMs} aria-label="Pausa dopo la frase" onChange={(e) => update({ pauseMs: Number(e.target.value) })} />
      </Row>
      <Row><Toggle label="Virgola come pausa piena" checked={prefs.comma} onChange={(comma) => update({ comma })} /></Row>
      <Row><span>Lettera di fuoco</span><Segments label="Lettera di fuoco" value={prefs.orp} options={ORPS} onChange={(orp) => update({ orp })} /></Row>
      <Row><span>Passo indietro: <b className="font-normal">{prefs.step}</b> parole</span>
        <Segments label="Passo indietro" value={prefs.step} options={STEPS.map((n) => [n, `−${n}`] as const)} onChange={(step) => update({ step })} />
      </Row>
      {section('Aspetto')}
      <Row><div className="flex items-center justify-between">
        <span>Dimensione del testo <b className="font-normal">{prefs.size}</b></span>
        <div className="flex gap-1">
          <Pill aria-label="Testo più piccolo" onClick={() => update({ size: Math.max(24, prefs.size - 4) })}>−</Pill>
          <Pill aria-label="Testo più grande" onClick={() => update({ size: Math.min(96, prefs.size + 4) })}>+</Pill>
        </div>
      </div></Row>
      <Row><Toggle label="Font per dislessia" checked={prefs.dyslexic} onChange={(dyslexic) => update({ dyslexic })} /></Row>
      <Row><Toggle label="Modalità Irlen" checked={prefs.irlen !== null} onChange={(on) => update({ irlen: on ? 'pesca' : null })} />
        {prefs.irlen && <Segments label="Sfondo" value={prefs.irlen} options={TINTS} onChange={(irlen) => update({ irlen })} />}
      </Row>
      {section('Suono')}
      <Row><Toggle label="Suono" checked={prefs.sound} onChange={(sound) => update({ sound })} />
        <span>Tono <b className="font-normal">{prefs.pitch.toFixed(1)}</b>×</span>
        <input type="range" min={0.5} max={2} step={0.1} value={prefs.pitch} aria-label="Tono"
          onChange={(e) => { const pitch = Number(e.target.value); update({ pitch }); onPitch(pitch) }} />
      </Row>
      <Row><Toggle label="Rumore di fondo" checked={prefs.noise !== null}
          onChange={(on) => { update({ noise: on ? 'rosa' : null }); onPreviewNoise(on ? 'rosa' : null, prefs.noiseVolume) }} />
        {prefs.noise && <>
          <Segments label="Tipo di rumore" value={prefs.noise} options={NOISE_KINDS} onChange={(noise) => { update({ noise }); onPreviewNoise(noise, prefs.noiseVolume) }} />
          <input type="range" min={0} max={0.6} step={0.02} value={prefs.noiseVolume} aria-label="Volume del rumore"
            onChange={(e) => update({ noiseVolume: Number(e.target.value) })} />
        </>}
      </Row>
    </section>
  )
}

type NoiseKind = NonNullable<RsvpPreference['noise']>

/** Suoni generati con Web Audio: nessun file. L'AudioContext nasce al primo gesto. */
function createSound() {
  let ac: AudioContext | null = null
  let source: AudioBufferSourceNode | null = null
  let gain: GainNode | null = null
  let previewTimer: ReturnType<typeof setTimeout> | undefined
  const buffers = new Map<NoiseKind, AudioBuffer>()
  const context = () => {
    if (!ac) {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Ctor) return null
      try { ac = new Ctor() } catch { return null }
    }
    if (ac.state === 'suspended') void ac.resume()
    return ac
  }
  const stopNoise = () => {
    clearTimeout(previewTimer)
    try { source?.stop() } catch { /* già fermo */ }
    source = null
    gain = null
  }
  const noise = (kind: NoiseKind, volume: number) => {
    stopNoise()
    const audio = context()
    if (!audio) return
    let buffer = buffers.get(kind)
    if (!buffer) {
      buffer = noiseBuffer(audio, kind)
      buffers.set(kind, buffer)
    }
    source = audio.createBufferSource()
    source.buffer = buffer
    source.loop = true
    gain = audio.createGain()
    const t = audio.currentTime
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(Math.max(0.001, volume), t + 0.3)
    source.connect(gain).connect(audio.destination)
    source.start()
  }
  return {
    unlock: () => void context(),
    click(end: boolean, pitch: number) {
      const audio = context()
      if (!audio) return
      const t = audio.currentTime
      const base = (end ? 520 : 880) * pitch
      const duration = end ? 0.11 : 0.045
      const osc = audio.createOscillator()
      const env = audio.createGain()
      osc.type = 'triangle'
      osc.frequency.setValueAtTime(base, t)
      if (end) osc.frequency.exponentialRampToValueAtTime(base * 0.82, t + duration)
      env.gain.setValueAtTime(0.0001, t)
      env.gain.exponentialRampToValueAtTime(end ? 0.22 : 0.13, t + 0.004)
      env.gain.exponentialRampToValueAtTime(0.0001, t + duration)
      osc.connect(env).connect(audio.destination)
      osc.start(t)
      osc.stop(t + duration + 0.02)
    },
    noise,
    preview(kind: NoiseKind, volume: number) {
      noise(kind, volume)
      previewTimer = setTimeout(stopNoise, 2000)
    },
    volume(volume: number) {
      if (gain && ac) gain.gain.setTargetAtTime(Math.max(0.001, volume), ac.currentTime, 0.05)
    },
    stopNoise,
    dispose() {
      stopNoise()
      void ac?.close().catch(() => {})
      ac = null
    },
  }
}

/** Due secondi di rumore bianco, rosa (filtro di Paul Kellet) o marrone, da ripetere in loop. */
function noiseBuffer(audio: AudioContext, kind: NoiseKind): AudioBuffer {
  const length = audio.sampleRate * 2
  const buffer = audio.createBuffer(1, length, audio.sampleRate)
  const data = buffer.getChannelData(0)
  let last = 0
  let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0
  for (let i = 0; i < length; i++) {
    const white = Math.random() * 2 - 1
    if (kind === 'bianco') data[i] = white * 0.5
    else if (kind === 'marrone') {
      last = (last + 0.02 * white) / 1.02
      data[i] = last * 3.2
    } else {
      b0 = 0.99886 * b0 + white * 0.0555179
      b1 = 0.99332 * b1 + white * 0.0750759
      b2 = 0.969 * b2 + white * 0.153852
      b3 = 0.8665 * b3 + white * 0.3104856
      b4 = 0.55 * b4 + white * 0.5329522
      b5 = -0.7616 * b5 - white * 0.016898
      data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11
      b6 = white * 0.115926
    }
  }
  return buffer
}
