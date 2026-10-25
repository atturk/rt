import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RSVP_DEFAULT, type RsvpPreference } from '@/lib/studyPrefs'
import { SpeedReader } from './SpeedReader'

let mockPrefs: RsvpPreference = { ...RSVP_DEFAULT, sound: false }
const mockSave = vi.fn((next: RsvpPreference) => {
  mockPrefs = next
})

vi.mock('@/lib/studyPrefs', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/studyPrefs')>(),
  useRsvpPrefs: () => [mockPrefs, mockSave],
}))

const mockNoise = vi.fn()
const mockStopNoise = vi.fn()
const mockClick = vi.fn()
vi.mock('./rsvpSound', () => ({
  createSound: () => ({
    unlock: vi.fn(),
    click: mockClick,
    noise: mockNoise,
    preview: vi.fn(),
    volume: vi.fn(),
    stopNoise: mockStopNoise,
    dispose: vi.fn(),
  }),
  FADE_S: 1,
}))

beforeEach(() => {
  mockPrefs = { ...RSVP_DEFAULT, sound: false }
  vi.clearAllMocks()
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('rilegge le evidenziazioni modificate mentre il lettore è aperto', async () => {
  const source = document.createElement('div')
  source.innerHTML = '<p>Prima parola.</p>'
  render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)
  expect(screen.getByTestId('speed-reader-word')).not.toHaveAttribute('data-hl')
  await act(async () => { source.innerHTML = '<p><span class="rt-hl rt-hl-4">Prima</span> parola.</p>' })
  await waitFor(() => expect(screen.getByTestId('speed-reader-word')).toHaveAttribute('data-hl', 'true'))
  expect(screen.getByTestId('speed-reader-context').querySelector('.rt-rsvp-hl')).toHaveTextContent('Prima')
  await act(async () => { source.querySelector('span')!.className = '' })
  await waitFor(() => expect(screen.getByTestId('speed-reader-word')).not.toHaveAttribute('data-hl'))
})

it('con autoStart vero avvia la lettura e mostra il pannello attenuato', async () => {
  const source = document.createElement('div')
  source.innerHTML = '<p>Prima parola di test.</p>'
  render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={true} canNextUnit={true} autoStart={true} />)
  expect(screen.getByTestId('speed-reader-panel')).toHaveClass('opacity-25')
  expect(screen.getByRole('button', { name: 'Pausa' })).toBeInTheDocument()
})

describe('conto alla rovescia e rumore con dissolvenza (4.3.3b3 piano 7)', () => {
  it('con countdown 0 la prima parola parte subito', () => {
    mockPrefs = { ...RSVP_DEFAULT, countdown: 0, sound: false }
    const source = document.createElement('div')
    source.innerHTML = '<p>Prima parola di test.</p>'
    render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(screen.queryByTestId('speed-reader-countdown')).not.toBeInTheDocument()
    expect(screen.getByTestId('speed-reader-word')).toBeInTheDocument()
  })

  it('con 3 compaiono 3, 2, 1 e poi la prima parola, e il rumore parte al Play (non dopo)', () => {
    vi.useFakeTimers()
    mockPrefs = { ...RSVP_DEFAULT, countdown: 3, noise: 'rosa', sound: false }
    const source = document.createElement('div')
    source.innerHTML = '<p>Prima parola di test.</p>'
    render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    // Il rumore parte subito al Play
    expect(mockNoise).toHaveBeenCalledWith('rosa', expect.any(Number))

    // Compare 3
    expect(screen.getByTestId('speed-reader-countdown')).toHaveTextContent('3')

    // Dopo 1 s -> 2
    act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.getByTestId('speed-reader-countdown')).toHaveTextContent('2')

    // Dopo 1 s -> 1
    act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.getByTestId('speed-reader-countdown')).toHaveTextContent('1')

    // A fine conto -> prima parola
    act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByTestId('speed-reader-countdown')).not.toBeInTheDocument()
    expect(screen.getByTestId('speed-reader-word')).toBeInTheDocument()
  })

  it('pausa e ripresa entro 4 s → niente conto; dopo 6 s → conto di nuovo; nuova unità → conto di nuovo', () => {
    vi.useFakeTimers()
    mockPrefs = { ...RSVP_DEFAULT, countdown: 3, noise: 'rosa', sound: false }
    let source = document.createElement('div')
    source.innerHTML = '<p>Prima parola di test.</p>'
    const { rerender } = render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)

    // 1. Avvia e completa il primo countdown
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    act(() => { vi.advanceTimersByTime(3000) })
    expect(screen.queryByTestId('speed-reader-countdown')).not.toBeInTheDocument()

    // 2. Metti in pausa
    fireEvent.click(screen.getByRole('button', { name: 'Pausa' }))
    expect(mockStopNoise).toHaveBeenCalled()

    // 3. Ripresa dopo 4 s (entro 5 s) -> nessun conto alla rovescia
    act(() => { vi.advanceTimersByTime(4000) })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(screen.queryByTestId('speed-reader-countdown')).not.toBeInTheDocument()
    expect(screen.getByTestId('speed-reader-word')).toBeInTheDocument()

    // 4. Metti di nuovo in pausa
    fireEvent.click(screen.getByRole('button', { name: 'Pausa' }))

    // 5. Ripresa dopo 6 s (> 5 s) -> conto alla rovescia di nuovo
    act(() => { vi.advanceTimersByTime(6000) })
    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(screen.getByTestId('speed-reader-countdown')).toHaveTextContent('3')
    act(() => { vi.advanceTimersByTime(3000) })
    expect(screen.queryByTestId('speed-reader-countdown')).not.toBeInTheDocument()

    // 6. Nuova unità: resetta e fa il conto alla rovescia di nuovo
    source = document.createElement('div')
    source.innerHTML = '<p>Nuova unità con altro testo.</p>'
    rerender(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Avvia' }))
    expect(screen.getByTestId('speed-reader-countdown')).toHaveTextContent('3')
  })

  it('la preferenza si salva e si rilegge (0–10)', () => {
    vi.useFakeTimers()
    mockPrefs = { ...RSVP_DEFAULT, countdown: 3, sound: false }
    const source = document.createElement('div')
    source.innerHTML = '<p>Prima parola di test.</p>'
    render(<SpeedReader source={source} active context settings={true} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} onUnit={vi.fn()} canPrevUnit={false} canNextUnit={true} />)

    const slider = screen.getByLabelText('Conto alla rovescia')
    expect(slider).toHaveAttribute('min', '0')
    expect(slider).toHaveAttribute('max', '10')

    // Imposta a 5 s
    fireEvent.change(slider, { target: { value: '5' } })
    expect(screen.getByText('5 s')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(500) })
    expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ countdown: 5 }))

    // Imposta a 0 -> Spento
    fireEvent.change(slider, { target: { value: '0' } })
    expect(screen.getByText('Spento')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(500) })
    expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ countdown: 0 }))
  })
})

