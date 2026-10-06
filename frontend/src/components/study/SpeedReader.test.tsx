import { act, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { RSVP_DEFAULT } from '@/lib/studyPrefs'
import { SpeedReader } from './SpeedReader'

vi.mock('@/lib/studyPrefs', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/studyPrefs')>(),
  useRsvpPrefs: () => [{ ...RSVP_DEFAULT, sound: false }, vi.fn()],
}))
beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
})
afterEach(() => vi.unstubAllGlobals())

it('rilegge le evidenziazioni modificate mentre il lettore è aperto', async () => {
  const source = document.createElement('div')
  source.innerHTML = '<p>Prima parola.</p>'
  render(<SpeedReader source={source} active context settings={false} onSettingsChange={vi.fn()} settingsButton={{ current: null }} blocked={false} questions={0} onReview={vi.fn()} onGenerate={vi.fn()} onTintChange={vi.fn()} onClose={vi.fn()} />)
  expect(screen.getByTestId('speed-reader-word')).not.toHaveAttribute('data-hl')
  await act(async () => { source.innerHTML = '<p><span class="rt-hl rt-hl-4">Prima</span> parola.</p>' })
  await waitFor(() => expect(screen.getByTestId('speed-reader-word')).toHaveAttribute('data-hl', 'true'))
  expect(screen.getByTestId('speed-reader-context').querySelector('.rt-rsvp-hl')).toHaveTextContent('Prima')
  await act(async () => { source.querySelector('span')!.className = '' })
  await waitFor(() => expect(screen.getByTestId('speed-reader-word')).not.toHaveAttribute('data-hl'))
})
