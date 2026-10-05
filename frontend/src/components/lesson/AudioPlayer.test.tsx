import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PREFERENCES_KEY } from '@/lib/preferences'
import { vi } from 'vitest'

import { AudioPlayer } from './AudioPlayer'
import { AudioProvider } from './audio'

const play = vi.fn(() => Promise.resolve())
const pause = vi.fn()

beforeEach(() => {
  localStorage.clear()
  play.mockClear()
  pause.mockClear()
  vi.spyOn(api, 'GET').mockImplementation(() => Promise.resolve({ data: { 'audio.rate': JSON.parse(localStorage.getItem('rt-pref:audio.rate') ?? '1') }, response: new Response(null, { status: 200 }) }) as never)
  vi.spyOn(api, 'PUT').mockResolvedValue({ response: new Response(null, { status: 204 }) } as never)
})

afterEach(() => vi.restoreAllMocks())

function renderPlayer() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const cached = localStorage.getItem('rt-pref:audio.rate')
  client.setQueryData(PREFERENCES_KEY, { 'audio.rate': cached ? JSON.parse(cached) : 1 })
  render(
    <QueryClientProvider client={client}><AudioProvider>
      <AudioPlayer lessonId={4} sections={[{ unit_id: '1.1', start_seconds: 0 }, { unit_id: '1.2', start_seconds: 60 }, { unit_id: '1.3', start_seconds: 120 }]} />
    </AudioProvider></QueryClientProvider>,
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
    localStorage.setItem('rt-pref:audio.rate', '1.25')
    const audio = renderPlayer()
    expect(audio).toHaveAttribute('src', '/api/v1/lessons/4/audio')
    expect(screen.getByRole('button', { name: 'Velocità di riproduzione: 1,25×' })).toBeInTheDocument()
    expect(audio.playbackRate).toBe(1.25)
  })

  it('il pulsante velocità gira fra i valori fissi, applica e salva la scelta su RT', async () => {
    const audio = renderPlayer()
    const speed = screen.getByTestId('speed-button')
    expect(speed).toHaveTextContent('1×')
    for (const [label, rate] of [['1,25×', 1.25], ['1,5×', 1.5], ['1,75×', 1.75], ['2×', 2], ['1×', 1]] as const) {
      fireEvent.click(speed)
      await waitFor(() => expect(speed).toHaveTextContent(label))
      expect(audio.playbackRate).toBe(rate)
      expect(localStorage.getItem('rt-pref:audio.rate')).toBe(String(rate))
      await waitFor(() => expect(api.PUT).toHaveBeenLastCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'audio.rate' } }, body: rate }))
    }
  })

  it('la barra della posizione sposta l\'audio; le frecce di 5 secondi', () => {
    const audio = renderPlayer()
    fireEvent.loadedMetadata(audio)
    const seek = screen.getByRole('slider', { name: "Posizione nell'audio" })
    fireEvent.change(seek, { target: { value: '60' } })
    expect(audio.currentTime).toBe(60)
    expect(screen.getByTestId('audio-current')).toHaveTextContent('1:00')
    fireEvent.keyDown(seek, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(65)
    expect(play).not.toHaveBeenCalled()
  })

  it('con il mouse sul riquadro le frecce saltano di 5 secondi, fuori no', () => {
    const audio = renderPlayer()
    fireEvent.loadedMetadata(audio)
    audio.currentTime = 30
    const player = screen.getByTestId('audio-player')
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(30)
    fireEvent.mouseEnter(player)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(35)
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(audio.currentTime).toBe(25)
    fireEvent.mouseLeave(player)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(25)
  })

  // Regressione: il player leggeva l'elemento audio durante il render, quando al primo render è
  // ancora null, e finché qualcosa non lo ridisegnava Riproduci non faceva nulla.
  it('Riproduci avvia l\'audio appena montato il player', () => {
    renderPlayer()
    fireEvent.click(screen.getByRole('button', { name: 'Riproduci' }))
    expect(play).toHaveBeenCalledTimes(1)
  })

  it('se il browser non riesce a riprodurre lo dice', () => {
    const audio = renderPlayer()
    fireEvent.error(audio)
    expect(screen.getByText('Il browser non riesce a riprodurre questo audio.')).toBeInTheDocument()
  })
})
