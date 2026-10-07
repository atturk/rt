import { vi } from 'vitest'
import { createSound } from './rsvpSound'

function audioContext() {
  const param = () => ({ setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn(), setTargetAtTime: vi.fn() })
  const node = () => ({ connect: vi.fn(function (this: unknown, target: unknown) { return target }), start: vi.fn(), stop: vi.fn() })
  const audio = {
    currentTime: 10, sampleRate: 48000, state: 'running', destination: {}, close: vi.fn(async () => undefined),
    createGain: vi.fn(() => ({ ...node(), gain: param() })),
    createOscillator: vi.fn(() => ({ ...node(), type: '', frequency: param() })),
    createBiquadFilter: vi.fn(() => ({ ...node(), type: '', frequency: param(), Q: param() })),
    createBufferSource: vi.fn(() => ({ ...node(), buffer: null })),
    createBuffer: vi.fn((_channels: number, frames: number) => ({ getChannelData: () => new Float32Array(frames) })),
  }
  vi.stubGlobal('AudioContext', vi.fn(function () { return audio }))
  return audio
}
afterEach(() => vi.unstubAllGlobals())

it.each([
  ['classico', false, 'triangle', 880, 880, .13, .004, .045],
  ['classico', true, 'triangle', 520, 520 * .82, .22, .004, .11],
  ['tick', false, 'sine', 1000, 940, .2, .004, .035],
  ['tick', true, 'sine', 620, 480, .3, .006, .12],
  ['legno', false, 'sine', 760, 700, .14, .002, .03],
  ['legno', true, 'sine', 380, 330, .32, .003, .11],
] as const)('clic %s, grave %s: frequenze e inviluppo esatti', (kind, grave, type, from, to, peak, attack, decay) => {
  const audio = audioContext()
  const sound = createSound()
  sound.click(grave, 1.5, kind)
  const osc = audio.createOscillator.mock.results[0].value
  const env = audio.createGain.mock.results.at(-1)!.value
  expect(osc.type).toBe(type)
  expect(osc.frequency.setValueAtTime).toHaveBeenCalledWith(from * 1.5, 10)
  if (to !== from) expect(osc.frequency.exponentialRampToValueAtTime).toHaveBeenCalledWith(to * 1.5, 10 + decay)
  expect(env.gain.setValueAtTime).toHaveBeenCalledWith(.0001, 10)
  expect(env.gain.exponentialRampToValueAtTime.mock.calls).toEqual([[peak, 10 + attack], [.0001, 10 + decay]])
  expect(osc.start).toHaveBeenCalledWith(10)
  expect(osc.stop).toHaveBeenCalledWith(10 + decay + .02)
  if (kind === 'classico') expect(audio.createBiquadFilter).not.toHaveBeenCalled()
  else {
    const filter = audio.createBiquadFilter.mock.results[0].value
    expect(filter.type).toBe(kind === 'tick' ? 'lowpass' : 'bandpass')
    expect(filter.frequency.setValueAtTime).toHaveBeenCalledWith(kind === 'tick' ? 2600 : (grave ? 900 : 2200) * 1.5, 10)
    if (kind === 'legno') {
      expect(filter.Q.setValueAtTime).toHaveBeenCalledWith(grave ? 3 : 5, 10)
      const noiseEnv = audio.createGain.mock.results[0].value
      expect(noiseEnv.gain.exponentialRampToValueAtTime.mock.calls).toEqual([[grave ? .35 : .3, 10.001], [.0001, 10 + (grave ? .03 : .012)]])
      expect(audio.createBufferSource).toHaveBeenCalledTimes(1)
    }
  }
  sound.dispose()
})
it('Legno predefinito: il buffer bianco di 0,2 s si riusa', () => {
  const audio = audioContext()
  const sound = createSound()
  sound.click(false, 1); sound.click(true, 1); sound.click(false, 2)
  expect(audio.createBuffer).toHaveBeenCalledOnce()
  expect(audio.createBuffer).toHaveBeenCalledWith(1, 9600, 48000)
  const nodes = audio.createBufferSource.mock.results.map(r => r.value)
  expect(nodes[0].buffer).toBe(nodes[1].buffer)
  sound.dispose()
})
