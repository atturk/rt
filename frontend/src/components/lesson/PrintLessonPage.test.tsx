import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, it, vi } from 'vitest'

import { PrintLessonPage } from './PrintLessonPage'

vi.mock('@/api/hooks', () => ({
  useLesson: () => ({ data: { id: 1, materia: 'FISIOLOGIA', titolo: 'Acidosi', data: '2026-10-02' } }),
  useLessonDocument: () => ({
    data: {
      html: '<h3 data-unit-id="u1">Titolo</h3><p data-unit-timecode="u1">00:22</p><p>Testo</p>',
      sections: [{ unit_id: 'u1', start_formatted: '00:22' }],
    },
  }),
}))

it('il timecode compare una volta sola, accanto al titolo', async () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(container.querySelector('.print-timecode')).not.toBeNull())
  expect(screen.getByText('Testo')).toBeInTheDocument()
  expect(container.querySelector('[data-unit-timecode]')).toBeNull()
  const content = container.querySelector('.print-content')!
  expect(content.textContent!.match(/00:22/g)).toHaveLength(1)
  expect(container.querySelector('.print-timecode')).toHaveTextContent('00:22')
})
