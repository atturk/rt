import { render, screen } from '@testing-library/react'
import { UnitText } from './Study'
import type { StudyNote } from '@/api/studyNotes'

const notes = [1, 2].map((id) => ({
  id, kind: 'chiedi', unit_id: '1.1', anchor_state: 'trovata', current_quote: `Passaggio ${id}`,
})) as StudyNote[]
const unit = { id: '1.1', title: 'Test', html: '<p>Passaggio 1 e Passaggio 2</p>', questions: 0, pending: {}, status: 'da-imparare' as const }

it('sottolinea soltanto la nota aperta e rimuove il segno alla chiusura', () => {
  const onReady = vi.fn()
  const component = (id: number | null) => <UnitText lessonId={1} unit={unit} highlightMode={null} onReady={onReady} notes={notes} activeNoteId={id} />
  const view = render(component(null))
  const text = screen.getByTestId('study-text')
  expect(text.querySelector('.rt-sn')).toBeNull()
  view.rerender(component(2))
  expect(text.querySelectorAll('.rt-sn')).toHaveLength(1)
  expect(text.querySelector('.rt-sn')).toHaveTextContent('Passaggio 2')
  view.rerender(component(1))
  expect(text.querySelectorAll('.rt-sn')).toHaveLength(1)
  expect(text.querySelector('.rt-sn')).toHaveTextContent('Passaggio 1')
  view.rerender(component(null))
  expect(text.querySelector('.rt-sn')).toBeNull()
  expect(text).toHaveTextContent('Passaggio 1 e Passaggio 2')
})
