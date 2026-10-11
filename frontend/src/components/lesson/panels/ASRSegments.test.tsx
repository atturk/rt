import { fireEvent, render, screen } from '@testing-library/react'
import { ASRSegments } from './ASRSegments'

it('ordina i tratti, sottolinea solo le parole incerte e passa inizio e fine al player', () => {
  const seek = vi.fn()
  render(<ASRSegments onSeek={seek} segments={[
    { segment_id: 'b', start_s: 10, end_s: 13, text_raw: 'secondo' },
    { segment_id: 'a', start_s: 5, end_s: 7, text_raw: 'nota nota', confidence: .2, threshold: .35,
      uncertain_words: [{ start_char: 5, end_char: 9, confidence: .2 }] },
  ]} />)
  const cards = screen.getAllByTestId('asr-segment')
  expect(cards[0]).toHaveTextContent('0:05 – 0:07')
  expect(cards[0].querySelector('u')).toHaveTextContent('nota')
  expect(cards[0]).toHaveTextContent('Confidenza 0,2 · soglia della lezione 0,35')
  fireEvent.click(screen.getAllByRole('button', { name: 'Ascolta il tratto' })[0])
  expect(seek).toHaveBeenCalledWith(5, true, 7)
})
