import { ChevronLeft, Moon, Pause, Play, Rewind, RotateCcw, SlidersHorizontal, Sun } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { useIsPhone } from '@/lib/phone'
import { useRsvpPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import { cn } from '@/lib/utils'
import {
  MAX_WPM, MIN_WPM, focusIndex, formatRemaining, isFullStop, nextSentence, previousSentence, readUnitWords,
  remainingSeconds, surrounding, wordDelay,
} from './speedReader'

const RING = 2 * Math.PI * 50
const NOISE_KINDS = [['bianco', 'Bianco'], ['rosa', 'Rosa'], ['marrone', 'Marrone']] as const
const TINTS = [['pesca', 'Pesca'], ['menta', 'Menta'], ['pergamena', 'Pergamena']] as const
const ORPS = [['prima', 'Prima'], ['bilanciata', 'Bilanciata'], ['dopo', 'Dopo']] as const
const STEPS = [1, 3, 5, 10]

/**
 * Lettura veloce dell'unità aperta nello Studio (4.2.2, V1): una parola alla volta con la lettera
 * di fuoco sempre nello stesso punto, clic a ogni parola e uno più grave a fine frase.
 */
export function SpeedReader({ source, title, onClose }: { source: Element; title: string; onClose: () => void }) {
  const [saved, save] = useRsvpPrefs()
  const [prefs, setPrefs] = useState<RsvpPreference>(saved)
  const { words, paragraphs } = useMemo(() => readUnitWords(source), [source])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [day, setDay] = useState(() => !document.documentElement.classList.contains('dark'))
  const [context, setContext] = useState(false)
  const [settings, setSettings] = useState(false)
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
      persist.current = setTimeout(() => save(next), 400)
      return next
    })
  }, [save])
  useEffect(() => () => clearTimeout(persist.current), [])

  const word = words[index]?.text ?? ''
  const full = isFullStop(word, prefs.comma)

  useEffect(() => {
    if (!playing || !words[index]) return
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
  }, [playing, index, words, sound])

  // Il rumore suona durante la lettura; in pausa solo l'anteprima di 2 s delle impostazioni.
  useEffect(() => {
    if (!playing || !prefs.noise) return
    sound.noise(prefs.noise, prefsRef.current.noiseVolume)
    return () => sound.stopNoise()
  }, [playing, prefs.noise, sound])
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
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const field = e.target instanceof Element && e.target.closest('input:not([type=range]), textarea, select')
      if (field && e.key !== 'Escape') return
      const keys: Record<string, () => void> = {
        ' ': toggle,
        ArrowLeft: () => jump(previousSentence(words, index)),
        ArrowRight: () => jump(nextSentence(words, index)),
        ArrowUp: () => update({ wpm: Math.min(MAX_WPM, prefsRef.current.wpm + 25) }),
        ArrowDown: () => update({ wpm: Math.max(MIN_WPM, prefsRef.current.wpm - 25) }),
        Home: () => { setPlaying(false); setIndex(0) },
        Escape: () => (settings ? setSettings(false) : onClose()),
      }
      const action = keys[e.key]
      if (!action) return
      // Spazio su un pulsante lo premerebbe due volte.
      e.preventDefault()
      e.stopPropagation()
      action()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [toggle, jump, update, words, index, settings, onClose])

  const around = surrounding(words, index)
  const k = word ? focusIndex(word, prefs.orp) : 0
  const remaining = remainingSeconds(words.length, index, prefs.wpm)
  const progress = words.length ? (index + 1) / words.length : 0
  const animate = playing && full && !matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const para = paragraphs[words[index]?.para ?? 0] ?? []

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Lettura veloce"
      data-testid="speed-reader"
      data-day={day && !prefs.irlen ? '' : undefined}
      data-tint={prefs.irlen ?? undefined}
      data-theme-mode={day ? 'giorno' : 'notte'}
      className="rt-rsvp fixed inset-0 z-50 flex flex-col gap-2 px-[22px] pb-3.5 pt-[18px] max-md:px-3.5 max-md:pb-[calc(10px+env(safe-area-inset-bottom))] max-md:pt-3"
    >
      <div className="flex items-center gap-2.5">
        <Pill onClick={onClose} aria-label="Torna allo Studio"><ChevronLeft className="size-4" aria-hidden />Studio</Pill>
        <div className="min-w-0 flex-1 truncate text-center text-meta text-(--o-dim) max-md:invisible">{title}</div>
        <div role="group" aria-label="Tema della lettura veloce" className="inline-flex rounded-[9px] border border-(--o-line) bg-(--o-chip) p-0.5">
          {([[true, 'Giorno', Sun], [false, 'Notte', Moon]] as const).map(([value, label, Icon]) => (
            <button key={label} type="button" aria-pressed={day === value} onClick={() => { setDay(value); if (prefs.irlen) update({ irlen: null }) }}
              className={cn('inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 font-mono text-meta text-(--o-dim)',
                day === value && 'bg-[color-mix(in_oklch,var(--o-focus)_22%,var(--o-panel))] text-(--o-fg)')}>
              <Icon className="size-3.5" aria-hidden /><span className="max-md:sr-only">{label}</span>
            </button>
          ))}
        </div>
        <Pill aria-pressed={context} onClick={() => setContext(!context)}>Contesto</Pill>
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-[18px]">
        {context && (
          <div data-testid="speed-reader-context" className="absolute left-1/2 top-0 z-[2] max-h-[45%] w-[min(680px,100%)] -translate-x-1/2 overflow-auto rounded-xl border border-(--o-line) bg-(--o-panel) px-3.5 py-2.5 text-body leading-[1.7] text-(--o-dim)">
            {para.map((piece, i) => (
              <span key={i} className={cn(piece.index !== null && piece.index < index && 'text-(--o-fg)',
                piece.index === index && 'font-semibold text-(--o-focus)')} data-current={piece.index === index || undefined}>
                {piece.text}{' '}
              </span>
            ))}
          </div>
        )}
        <div className="min-h-[1.5em] max-w-[92%] text-center text-[22px] leading-normal tracking-[0.14em] text-(--o-dim) max-md:text-base" data-testid="speed-reader-before">
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
        <div className="min-h-[1.5em] max-w-[92%] text-center text-[22px] leading-normal tracking-[0.14em] text-(--o-dim) max-md:text-base" data-testid="speed-reader-after">
          {playing ? '' : around.after}
        </div>
        {!words.length && <p className="text-body text-(--o-dim)">Questa unità non ha testo da leggere.</p>}
      </div>

      <div className="grid grid-cols-[auto_auto] items-center justify-center gap-x-5 gap-y-1 font-mono text-meta text-(--o-dim)">
        <span>Velocità <b className="font-normal text-(--o-fg)">{prefs.wpm}</b> parole/min</span>
        <button type="button" aria-label="Impostazioni della lettura veloce" aria-expanded={settings} onClick={() => setSettings(!settings)}
          className="inline-flex size-[30px] items-center justify-center rounded-lg bg-(--o-chip) text-(--o-fg)">
          <SlidersHorizontal className="size-4" aria-hidden />
        </button>
        <input type="range" min={MIN_WPM} max={MAX_WPM} step={25} value={prefs.wpm} aria-label="Velocità" className="col-span-2 w-[190px] justify-self-center"
          onChange={(e) => update({ wpm: Number(e.target.value) })} />
      </div>

      <div className="mt-1.5 flex items-center justify-center gap-[26px]">
        <RoundButton label={`Indietro di ${prefs.step} parole`} onClick={() => jump(index - prefs.step)} note={`−${prefs.step}`}>
          <Rewind className="size-5" fill="currentColor" aria-hidden />
        </RoundButton>
        <button type="button" onClick={toggle} aria-label={playing ? 'Pausa' : 'Avvia'} data-testid="speed-reader-play" autoFocus
          className="relative inline-flex size-[92px] items-center justify-center rounded-full border border-(--o-line) bg-(--o-bg) text-(--o-fg)">
          <svg className="absolute -inset-1.5 size-[104px] -rotate-90" viewBox="0 0 104 104" aria-hidden>
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--o-line)" />
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--o-focus)" strokeLinecap="round"
              strokeDasharray={RING} strokeDashoffset={RING * (1 - progress)} />
          </svg>
          {playing ? <Pause className="size-[26px]" fill="currentColor" aria-hidden /> : <Play className="size-[26px]" fill="currentColor" aria-hidden />}
        </button>
        <RoundButton label="Ricomincia l'unità" onClick={() => { setPlaying(false); setIndex(0) }}>
          <RotateCcw className="size-5" aria-hidden />
        </RoundButton>
      </div>
      <div className="mt-3 text-center font-mono text-[11px] text-(--o-dim)" data-testid="speed-reader-count">
        {words.length ? `${index + 1} / ${words.length} parole · ${formatRemaining(remaining)}` : ''}
      </div>
      {!phone && (
        <div className="text-center text-meta text-(--o-dim)">
          Spazio avvia e ferma · ← frase precedente · → frase successiva · ↑ ↓ velocità · Home ricomincia · Esc torna allo Studio
        </div>
      )}

      {settings && (
        <SettingsPanel phone={phone} prefs={prefs} update={update} onDone={() => setSettings(false)}
          onPreviewNoise={(kind, volume) => { if (!kind) sound.stopNoise(); else if (!playing) sound.preview(kind, volume) }} onPitch={(pitch) => sound.click(false, pitch)} />
      )}
    </div>
  )
}

function Pill({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...props}
      className={cn('inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-[9px] border border-(--o-line) bg-(--o-chip) px-3 text-meta text-(--o-fg) hover:border-(--o-dim) aria-pressed:border-(--o-dim)', className)}>
      {children}
    </button>
  )
}

function RoundButton({ label, onClick, note, children }: { label: string; onClick: () => void; note?: string; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} onClick={onClick}
      className="relative inline-flex size-[58px] items-center justify-center rounded-full border border-(--o-line) bg-(--o-chip) text-(--o-fg)">
      {children}
      {note && <small className="absolute -bottom-[18px] font-mono text-[10px] text-(--o-dim)">{note}</small>}
    </button>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={cn('relative h-[22px] w-10 shrink-0 rounded-full transition-colors', checked ? 'bg-success' : 'bg-(--o-line)')}>
      <span className={cn('absolute top-[3px] size-4 rounded-full bg-white transition-[left]', checked ? 'left-[21px]' : 'left-[3px]')} />
    </button>
  )
}

function Segments<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: readonly (readonly [T, string])[]; onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex rounded-[9px] bg-(--o-chip) p-[3px]">
      {options.map(([v, text]) => (
        <button key={String(v)} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={cn('flex-1 rounded-md px-2 py-1 text-meta text-(--o-fg)', value === v && 'bg-(--o-bg)')}>{text}</button>
      ))}
    </div>
  )
}

function Row({ children }: { children: ReactNode }) {
  return <div className="grid gap-[7px] border-b border-(--o-line) px-3.5 py-2.5 last:border-b-0">{children}</div>
}

function SettingsPanel({ phone, prefs, update, onDone, onPreviewNoise, onPitch }: {
  phone: boolean
  prefs: RsvpPreference
  update: (change: Partial<RsvpPreference>) => void
  onDone: () => void
  onPreviewNoise: (kind: RsvpPreference['noise'], volume: number) => void
  onPitch: (pitch: number) => void
}) {
  const head = (text: string, hint: string, control: ReactNode) => (
    <div className="flex items-center justify-between gap-2">
      <span>{text}<small className="block text-meta text-(--o-dim)">{hint}</small></span>{control}
    </div>
  )
  return (
    <section aria-label="Impostazioni della lettura veloce" data-testid="speed-reader-settings"
      className={cn('z-[3] overflow-auto border border-(--o-line) bg-(--o-panel) py-1 text-body shadow-[0_16px_40px_rgb(0_0_0/0.35)]',
        phone ? 'fixed inset-x-0 bottom-0 max-h-[75dvh] rounded-t-[14px] pb-[env(safe-area-inset-bottom)]' : 'absolute right-[22px] top-[62px] max-h-[calc(100%-80px)] w-[300px] rounded-[14px]')}>
      <Row><div className="flex items-center justify-between"><b className="font-semibold">Impostazioni</b><Pill onClick={onDone}>Fatto</Pill></div></Row>
      <Row>
        {head('Suono', 'un clic a ogni parola, più grave a fine frase', <Toggle label="Suono" checked={prefs.sound} onChange={(sound) => update({ sound })} />)}
        <span>Tono <b className="font-normal">{prefs.pitch.toFixed(1)}</b>×</span>
        <input type="range" min={0.5} max={2} step={0.1} value={prefs.pitch} aria-label="Tono"
          onChange={(e) => { const pitch = Number(e.target.value); update({ pitch }); onPitch(pitch) }} />
      </Row>
      <Row>{head('Font per dislessia', 'lettere più distinguibili', <Toggle label="Font per dislessia" checked={prefs.dyslexic} onChange={(dyslexic) => update({ dyslexic })} />)}</Row>
      <Row>
        {head('Modalità Irlen', 'sfondo colorato che affatica meno', <Toggle label="Modalità Irlen" checked={prefs.irlen !== null} onChange={(on) => update({ irlen: on ? 'pesca' : null })} />)}
        {prefs.irlen && <Segments label="Sfondo" value={prefs.irlen} options={TINTS} onChange={(irlen) => update({ irlen })} />}
      </Row>
      <Row>
        {head('Rumore di fondo', 'copre i rumori intorno', <Toggle label="Rumore di fondo" checked={prefs.noise !== null}
          onChange={(on) => { update({ noise: on ? 'rosa' : null }); onPreviewNoise(on ? 'rosa' : null, prefs.noiseVolume) }} />)}
        {prefs.noise && <>
          <Segments label="Tipo di rumore" value={prefs.noise} options={NOISE_KINDS} onChange={(noise) => { update({ noise }); onPreviewNoise(noise, prefs.noiseVolume) }} />
          <input type="range" min={0} max={0.6} step={0.02} value={prefs.noiseVolume} aria-label="Volume del rumore"
            onChange={(e) => update({ noiseVolume: Number(e.target.value) })} />
        </>}
      </Row>
      <Row>
        <span>Pausa dopo la frase <b className="font-normal">{prefs.pauseMs}</b> ms</span>
        <input type="range" min={0} max={1200} step={50} value={prefs.pauseMs} aria-label="Pausa dopo la frase" onChange={(e) => update({ pauseMs: Number(e.target.value) })} />
      </Row>
      <Row>
        <span>Lettera di fuoco<small className="block text-meta text-(--o-dim)">dove cade l'occhio nella parola</small></span>
        <Segments label="Lettera di fuoco" value={prefs.orp} options={ORPS} onChange={(orp) => update({ orp })} />
      </Row>
      <Row>{head('Virgola come pausa piena', ', ; : come un punto', <Toggle label="Virgola come pausa piena" checked={prefs.comma} onChange={(comma) => update({ comma })} />)}</Row>
      <Row>
        <span>Passo indietro: <b className="font-normal">{prefs.step}</b> parole</span>
        <Segments label="Passo indietro" value={prefs.step} options={STEPS.map((n) => [n, `−${n}`] as const)} onChange={(step) => update({ step })} />
      </Row>
      <Row>
        <div className="flex items-center justify-between">
          <span>Dimensione del testo <b className="font-normal">{prefs.size}</b></span>
          <div className="flex gap-1">
            <Pill aria-label="Testo più piccolo" onClick={() => update({ size: Math.max(24, prefs.size - 4) })}>−</Pill>
            <Pill aria-label="Testo più grande" onClick={() => update({ size: Math.min(96, prefs.size + 4) })}>+</Pill>
          </div>
        </div>
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
