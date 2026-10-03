import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ReviewPage } from './review'
import { ReviewsPage } from './reviews'

function Destination() { const l = useLocation(); return <p>{l.pathname}{l.search}{l.hash}</p> }
it('reindirizza la revisione nel pannello conservando issue e unità', () => {
  render(<MemoryRouter initialEntries={['/lezioni/5/revisione?issue=a#unit-1.2']}><Routes><Route path="/lezioni/:lessonId/revisione" element={<ReviewPage />} /><Route path="/lezioni/:lessonId" element={<Destination />} /></Routes></MemoryRouter>)
  expect(screen.getByText('/lezioni/5?issue=a&pannello=verifica#unit-1.2')).toBeInTheDocument()
})
it('reindirizza l’elenco delle revisioni alle lezioni', () => {
  render(<MemoryRouter initialEntries={['/review']}><Routes><Route path="/review" element={<ReviewsPage />} /><Route path="/lezioni" element={<Destination />} /></Routes></MemoryRouter>)
  expect(screen.getByText('/lezioni')).toBeInTheDocument()
})
