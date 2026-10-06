import { MessageCircleQuestion, Pause, Play, Rewind, RotateCcw, Sparkles, X, type LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'

import { useIsPhone } from '@/lib/phone'
import { useRsvpPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import { Checkbox } from '@/components/settings/common'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SlideToggle } from '@/components/ui/slide-toggle'
import { cn } from '@/lib/utils'
import { createSound } from './rsvpSound'
import {
  MAX_WPM, MIN_WPM, focusIndex, graveWord, formatRemaining, isFullStop, nextSentence, previousSentence, readUnitWords,
  remainingSeconds, surroundingEntries, wordDelay,
} from './rsvp'

const RING = 2 * Math.PI * 50
const NOISE_KINDS = [['bianco', 'Bianco'], ['rosa', 'Rosa'], ['marrone', 'Marrone']] as const
const TINTS = [['pesca', 'Pesca'], ['menta', 'Menta'], ['pergamena', 'Pergamena']] as const
const ORPS = [['prima', 'Prima'], ['bilanciata', 'Bilanciata'], ['dopo', 'Dopo']] as const
const STEPS = [1, 3, 5, 10]

/** Lettura veloce integrata nello Studio: conserva suoni, tasti e preferenze. */
export function SpeedReader({ source, active, context, settings, onSettingsChange, settingsButton, blocked, questions, onReview, onGenerate, onTintChange, onClose }: {
  source: Element; active: boolean; context: boolean; settings: boolean; onSettingsChange: (open: boolean) => void
  settingsButton: RefObject<HTMLElement | null>; blocked: boolean
  questions: number; onReview: () => void; onGenerate: () => void
  onTintChange: (tint: RsvpPreference['irlen']) => void; onClose: () => void
}) {
  const [saved, save] = useRsvpPrefs()
  const [prefs, setPrefs] = useState<RsvpPreference>(saved)
  const [{ words, paragraphs }, setText] = useState(() => readUnitWords(source))
  useEffect(() => {
    const observer = new MutationObserver(() => setText(readUnitWords(source)))
    observer.observe(source, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [source])
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
    const entry = words[index]
    const current = prefsRef.current
    const end = graveWord(entry, current)
    if (current.sound) sound.click(end, current.pitch, current.clickSound)
    const delay = wordDelay(entry, current, ramp.current)
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

  const around = surroundingEntries(words, index)
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
                piece.index === index && 'font-semibold text-(--rsvp-focus)', piece.hl && prefs.highlights && 'rt-rsvp-hl')} data-current={piece.index === index || undefined}>
                {piece.math ? <span dangerouslySetInnerHTML={{ __html: piece.math.html }} /> : piece.text}{' '}
              </span>
            ))}
          </div>
        )}
        <div className="min-h-[1.5em] max-w-[92%] text-center text-heading leading-normal text-muted-foreground max-md:text-body" data-testid="speed-reader-before">
          {playing ? '' : around.before.map((entry, i) => <span key={i} className={entry.hl && prefs.highlights ? 'rt-rsvp-hl' : undefined}>{entry.math ? <span dangerouslySetInnerHTML={{ __html: entry.math.html }} /> : entry.text}{' '}</span>)}
        </div>
        <div
          key={animate ? `out-${index}` : 'still'}
          className={cn('rt-rsvp-word', prefs.dyslexic && 'dyslexic', animate && 'out')}
          style={{ '--rsvp-size': `${phone ? Math.round(prefs.size * 0.6) : prefs.size}px`, '--rsvp-out': `${Math.max(250, prefs.pauseMs + 60000 / prefs.wpm)}ms` } as CSSProperties}
          data-testid="speed-reader-word"
          data-hl={words[index]?.hl && prefs.highlights || undefined}
          data-math={words[index]?.math ? true : undefined}
          data-kind={full ? 'fine' : 'normale'}
          aria-live="off"
        >
          {words[index]?.math ? <FormulaWord html={words[index].math!.html} /> : <><span className="pre"><span>{word.slice(0, k)}</span></span><span className="orp">{word.charAt(k)}</span><span className="post"><span>{word.slice(k + 1)}</span></span></>}
        </div>
        <div className="min-h-[1.5em] max-w-[92%] text-center text-heading leading-normal text-muted-foreground max-md:text-body" data-testid="speed-reader-after">
          {playing ? '' : around.after.map((entry, i) => <span key={i} className={entry.hl && prefs.highlights ? 'rt-rsvp-hl' : undefined}>{entry.math ? <span dangerouslySetInnerHTML={{ __html: entry.math.html }} /> : entry.text}{' '}</span>)}
        </div>
        {!words.length && <p className="text-body text-muted-foreground">Questa unità non ha testo da leggere.</p>}
      </div>

      <div className="grid grid-cols-1 items-center justify-items-center gap-x-5 gap-y-1 text-meta text-muted-foreground">
        <span>Velocità <b className="font-normal text-foreground">{prefs.wpm}</b> parole/min</span>
        <input type="range" min={MIN_WPM} max={MAX_WPM} step={25} value={prefs.wpm} aria-label="Velocità" className="w-[220px] accent-accent-foreground justify-self-center"
          onChange={(e) => update({ wpm: Number(e.target.value) })} />
      </div>

      <div className="mt-1.5 flex items-center justify-center gap-6 max-md:gap-4" data-testid="speed-reader-controls">
        <RoundButton label={`Indietro di ${prefs.step} parole`} icon={Rewind} onClick={() => jump(index - prefs.step)} note={`−${prefs.step}`} />
        <RoundButton label={playing ? 'Pausa' : 'Avvia'} icon={playing ? Pause : Play} onClick={toggle} note={playing ? 'Pausa' : 'Play'} primary testId="speed-reader-play" badge={
          <svg className="pointer-events-none absolute -inset-1.5 -rotate-90" style={{ width: 'calc(100% + 12px)', height: 'calc(100% + 12px)' }} viewBox="0 0 104 104" aria-hidden>
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--border)" />
            <circle cx="52" cy="52" r="50" fill="none" strokeWidth="2" stroke="var(--rsvp-focus)" strokeLinecap="round"
              strokeDasharray={RING} strokeDashoffset={RING * (1 - progress)} />
          </svg>
        } />
        <RoundButton label="Ricomincia l'unità" icon={RotateCcw} onClick={() => { setPlaying(false); setIndex(0) }} note="Ricomincia" />
        <RoundButton label={questions > 0 ? `Ripassa l'unità · ${questions} domande` : 'Genera domande su questa unità'}
          icon={questions > 0 ? MessageCircleQuestion : Sparkles} note={questions > 0 ? 'Ripassa' : 'Genera'}
          onClick={() => { setPlaying(false); if (questions > 0) onReview(); else onGenerate() }} />
      </div>
      <div className="mt-3 text-center text-meta text-muted-foreground" data-testid="speed-reader-count">
        {words.length ? `${index + 1} / ${words.length} parole · ${formatRemaining(remaining)}` : ''}
      </div>
      {settings && (
        <SettingsPanel anchor={settingsButton} phone={phone} prefs={prefs} update={update} onDone={closeSettings}
          onPreviewNoise={(kind, volume) => { if (!kind) sound.stopNoise(); else if (!playing) sound.preview(kind, volume) }} onPitch={(pitch) => sound.click(false, pitch, prefs.clickSound)} />
      )}
    </div>
  )
}

/** Riduce solo le formule che eccedono lo spazio del lettore, anche con la barra aperta. */
function FormulaWord({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ scale: 1, height: 0 })
  useLayoutEffect(() => {
    const container = ref.current
    const rendered = container?.firstElementChild as HTMLElement | null
    if (!container || !rendered) return
    const fit = () => {
      const scale = Math.min(1, container.clientWidth / (rendered.scrollWidth || 1))
      setSize({ scale, height: rendered.offsetHeight * scale })
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(container); observer.observe(rendered)
    return () => observer.disconnect()
  }, [html])
  return <div ref={ref} className="rt-rsvp-formula" style={{ height: size.height || undefined }}>
    <span className="rt-rsvp-math" style={{ transform: `scale(${size.scale})` }} dangerouslySetInnerHTML={{ __html: html }} />
  </div>
}

function Pill(props: React.ComponentProps<typeof Button>) { return <Button variant="outline" size="sm" {...props} /> }

function RoundButton({ label, icon, onClick, note, primary, badge, testId }: {
  label: string; icon: LucideIcon; onClick: () => void; note: string; primary?: boolean; badge?: ReactNode; testId?: string
}) {
  return <div className="flex flex-col items-center gap-2">
    <IconButton label={label} icon={icon} onClick={onClick} variant={primary ? 'solid' : 'ghost'} badge={badge} data-testid={testId}
      className={cn('size-14 min-w-14 rounded-full border border-border max-md:size-12 max-md:min-w-12 [&_svg]:size-5', !primary && 'bg-muted')} />
    <span className="text-meta text-muted-foreground">{note}</span>
  </div>
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
      <Row><span>Pausa sulle formule</span>
        <Segments label="Pausa sulle formule" value={prefs.formulaPause} options={[
          ['adattiva', 'Adattiva'], ['standard', 'Standard'], ['personalizzata', 'Personalizzata'],
        ]} onChange={(formulaPause) => update({ formulaPause })} />
        {prefs.formulaPause === 'personalizzata' && <>
          <span>Formule complesse · {(prefs.formulaMs / 1000).toFixed(1).replace('.', ',')} s</span>
          <input type="range" min={500} max={5000} step={250} value={prefs.formulaMs} aria-label="Formule complesse"
            onChange={e => update({ formulaMs: Number(e.target.value) })} />
        </>}
      </Row>
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
      <Row><Toggle label="Mostra le evidenziazioni" checked={prefs.highlights} onChange={highlights => update({ highlights })} /></Row>
      <Row><Toggle label="Rallenta sulle evidenziate" checked={prefs.slowHighlights} onChange={slowHighlights => update({ slowHighlights })} /></Row>
      {section('Suono')}
      <Row><Toggle label="Suono" checked={prefs.sound} onChange={(sound) => update({ sound })} />
        {prefs.sound && <><span>Tipo di clic</span><Segments label="Tipo di clic" value={prefs.clickSound} options={[
          ['legno', 'Legno'], ['tick', 'Tick morbido'], ['classico', 'Classico'],
        ]} onChange={clickSound => update({ clickSound })} /></>}
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
