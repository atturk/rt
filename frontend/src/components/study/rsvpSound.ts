import type { RsvpPreference } from '@/lib/studyPrefs'

type NoiseKind = NonNullable<RsvpPreference['noise']>

/** Suoni generati con Web Audio: nessun file. L'AudioContext nasce al primo gesto. */
export function createSound() {
  let ac: AudioContext | null = null
  let source: AudioBufferSourceNode | null = null
  let gain: GainNode | null = null
  let previewTimer: ReturnType<typeof setTimeout> | undefined
  let clickBuffer: AudioBuffer | null = null
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
    click(end: boolean, pitch: number, kind: RsvpPreference['clickSound'] = 'legno') {
      const audio = context()
      if (!audio) return
      const t = audio.currentTime
      const envelope = (peak: number, attack: number, decay: number) => {
        const env = audio.createGain()
        env.gain.setValueAtTime(0.0001, t)
        env.gain.exponentialRampToValueAtTime(peak, t + attack)
        env.gain.exponentialRampToValueAtTime(0.0001, t + decay)
        env.connect(audio.destination)
        return env
      }
      const tone = (type: OscillatorType, from: number, to: number, peak: number, attack: number, decay: number, lowpass = false) => {
        const osc = audio.createOscillator()
        osc.type = type
        osc.frequency.setValueAtTime(from * pitch, t)
        if (to !== from) osc.frequency.exponentialRampToValueAtTime(to * pitch, t + decay)
        const env = envelope(peak, attack, decay)
        if (lowpass) {
          const filter = audio.createBiquadFilter()
          filter.type = 'lowpass'
          filter.frequency.setValueAtTime(2600, t)
          osc.connect(filter).connect(env)
        } else osc.connect(env)
        osc.start(t)
        osc.stop(t + decay + 0.02)
      }
      if (kind === 'classico') {
        const base = end ? 520 : 880
        tone('triangle', base, end ? base * 0.82 : base, end ? 0.22 : 0.13, 0.004, end ? 0.11 : 0.045)
      } else if (kind === 'tick') {
        tone('sine', end ? 620 : 1000, end ? 480 : 940, end ? 0.3 : 0.2, end ? 0.006 : 0.004, end ? 0.12 : 0.035, true)
      } else {
        if (!clickBuffer) {
          clickBuffer = audio.createBuffer(1, Math.round(audio.sampleRate * 0.2), audio.sampleRate)
          const samples = clickBuffer.getChannelData(0)
          for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1
        }
        const click = audio.createBufferSource()
        click.buffer = clickBuffer
        const filter = audio.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.setValueAtTime((end ? 900 : 2200) * pitch, t)
        filter.Q.setValueAtTime(end ? 3 : 5, t)
        const decay = end ? 0.03 : 0.012
        click.connect(filter).connect(envelope(end ? 0.35 : 0.3, 0.001, decay))
        click.start(t)
        click.stop(t + decay + 0.02)
        tone('sine', end ? 380 : 760, end ? 330 : 700, end ? 0.32 : 0.14, end ? 0.003 : 0.002, end ? 0.11 : 0.03)
      }
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
      clickBuffer = null
      buffers.clear()
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
