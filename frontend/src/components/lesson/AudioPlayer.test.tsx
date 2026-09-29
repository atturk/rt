import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { AudioPlayer } from './AudioPlayer'
import { AudioProvider } from './audio'

vi.mock('@/api/hooks', () => ({ useWaveform: () => ({ data: { ready: true, peaks: [10, 20, 30] } }) }))

const play = vi.fn(() => Promise.resolve())
const pause = vi.fn()

beforeAll(() => {
  // jsdom non ha ResizeObserver, canvas e riproduzione: bastano stub che non fanno nulla.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterAll(() => vi.restoreAllMocks())

beforeEach(() => {
  localStorage.clear()
  play.mockClear()
  pause.mockClear()
})

function renderPlayer() {
  render(
    <AudioProvider>
      <AudioPlayer lessonId={4} sections={[{ unit_id: '1.1', start_seconds: 0 }, { unit_id: '1.2', start_seconds: 60 }, { unit_id: '1.3', start_seconds: 120 }]} />
    </AudioProvider>,
  )
  const audio = screen.getByTestId('audio-player').querySelector('audio') as HTMLAudioElement
  Object.defineProperty(audio, 'readyState', { configurable: true, value: HTMLMediaElement.HAVE_METADATA })
  Object.defineProperty(audio, 'duration', { configurable: true, value: 300 })
  Object.defineProperty(audio, 'paused', { configurable: true, get: () => !play.mock.calls.length })
  audio.play = play
  audio.pause = pause
  return audio
}

describe('AudioPlayer', () => {
  it("carica l'audio della lezione e riprende la velocità salvata", () => {
    localStorage.setItem('rt-playback-rate', '1.25')
    const audio = renderPlayer()
    expect(audio).toHaveAttribute('src', '/api/v1/lessons/4/audio')
    expect(screen.getByRole('button', { name: 'Velocità di riproduzione: 1.25×' })).toBeInTheDocument()
    expect(audio.playbackRate).toBe(1.25)
  })

  it('la velocità si cambia dallo slider, si salva e il popover si chiude con Esc', () => {
    const audio = renderPlayer()
    const toggle = screen.getByRole('button', { name: /Velocità di riproduzione/ })
    fireEvent.click(toggle)
    fireEvent.change(screen.getByLabelText('Velocità di riproduzione'), { target: { value: '1.5' } })
    expect(screen.getByTestId('speed-value')).toHaveTextContent('1.5×')
    expect(audio.playbackRate).toBe(1.5)
    expect(localStorage.getItem('rt-playback-rate')).toBe('1.5')
    fireEvent.keyDown(screen.getByTestId('speed-popover'), { key: 'Escape' })
    expect(screen.queryByTestId('speed-popover')).toBeNull()
    expect(toggle).toHaveFocus()
  })

  it("i pulsanti di unità saltano all'inizio della successiva e della precedente", () => {
    const audio = renderPlayer()
    fireEvent.click(screen.getByRole('button', { name: 'Unità successiva' }))
    expect(audio.currentTime).toBe(60)
    expect(screen.getByTestId('audio-current')).toHaveTextContent('1:00')
    expect(play).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Unità successiva' }))
    expect(audio.currentTime).toBe(120)
    fireEvent.click(screen.getByRole('button', { name: 'Unità precedente' }))
    expect(audio.currentTime).toBe(60)
  })

  // Regressione: il player leggeva l'elemento audio durante il render, quando al primo render è
  // ancora null, e finché qualcosa non lo ridisegnava Riproduci non faceva nulla.
  it('Riproduci avvia l\'audio appena montato il player', () => {
    renderPlayer()
    fireEvent.click(screen.getByRole('button', { name: 'Riproduci' }))
    expect(play).toHaveBeenCalledTimes(1)
  })

  it('da fermo, i salti di 15 secondi spostano la posizione senza avviare la riproduzione', () => {
    const audio = renderPlayer()
    fireEvent.click(screen.getByRole('button', { name: 'Avanti di 15 secondi' }))
    expect(audio.currentTime).toBe(15)
    expect(play).not.toHaveBeenCalled()
  })

  it('se il browser non riesce a riprodurre lo dice', () => {
    const audio = renderPlayer()
    fireEvent.error(audio)
    expect(screen.getByText('Il browser non riesce a riprodurre questo audio.')).toBeInTheDocument()
  })
})
