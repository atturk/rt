import { act, fireEvent, render, screen } from '@testing-library/react'
import { AudioProvider, useLessonAudio } from './audio'

function Player() {
  const { audioRef, seek } = useLessonAudio()
  return <><audio ref={audioRef} data-testid="audio" /><button onClick={() => seek(5, true, 7)}>Tratto</button><button onClick={() => seek(10)}>Altro</button></>
}

it('ascolta il tratto fino alla fine e un altro seek cancella il limite', async () => {
  render(<AudioProvider><Player /></AudioProvider>)
  const audio = screen.getByTestId('audio') as HTMLAudioElement
  Object.defineProperty(audio, 'readyState', { value: 1 })
  const play = vi.spyOn(audio, 'play').mockResolvedValue()
  const pause = vi.spyOn(audio, 'pause').mockImplementation(() => undefined)
  fireEvent.click(screen.getByText('Tratto'))
  expect(audio.currentTime).toBe(5)
  expect(play).toHaveBeenCalledOnce()
  audio.currentTime = 6.5
  fireEvent.timeUpdate(audio)
  expect(pause).not.toHaveBeenCalled()
  audio.currentTime = 7.2
  fireEvent.timeUpdate(audio)
  expect(pause).toHaveBeenCalledOnce()
  expect(audio.currentTime).toBe(7)
  fireEvent.click(screen.getByText('Tratto'))
  fireEvent.click(screen.getByText('Altro'))
  audio.currentTime = 12
  fireEvent.timeUpdate(audio)
  expect(pause).toHaveBeenCalledOnce()
  await act(async () => undefined)
})

it('un nuovo seek sostituisce il tratto in attesa dei metadati', () => {
  render(<AudioProvider><Player /></AudioProvider>)
  const audio = screen.getByTestId('audio') as HTMLAudioElement
  vi.spyOn(audio, 'play').mockResolvedValue()
  fireEvent.click(screen.getByText('Tratto'))
  fireEvent.click(screen.getByText('Altro'))
  fireEvent.loadedMetadata(audio)
  expect(audio.currentTime).toBe(10)
})
