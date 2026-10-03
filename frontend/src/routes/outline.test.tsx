import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { OutlinePage } from './jobs'

function Destination() { const l = useLocation(); return <p>{l.pathname}{l.search}{l.hash}</p> }
it('i vecchi link alla scaletta portano alla lezione conservando query e unità', () => {
  render(<MemoryRouter initialEntries={['/lezioni/5/outline?from=job#unit-1.2']}><Routes><Route path="/lezioni/:lessonId/outline" element={<OutlinePage />} /><Route path="/lezioni/:lessonId" element={<Destination />} /></Routes></MemoryRouter>)
  expect(screen.getByText('/lezioni/5?from=job#unit-1.2')).toBeInTheDocument()
})
