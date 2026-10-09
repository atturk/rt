import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DocumentMenu } from './DocumentMenu'
const run = vi.hoisted(() => vi.fn())
vi.mock('@/api/hooks', () => ({ useRunJob: () => ({ mutate: run }) }))
vi.mock('@/api/enrichment', () => ({ useEnrichmentActions: () => ({ generate: {} }) }))
it.each([['1.2'], ['1.2', '1.3']])('dice le unità %j e tiene la verifica contestuale in arrivo', (...units: string[]) => {
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={units} ready locate={() => ({ text: 'Testo selezionato', units, anchor: { x: 0, y: 0 } })}><p>Documento</p></DocumentMenu></MemoryRouter>)
  fireEvent.contextMenu(screen.getByText('Documento'))
  expect(screen.getByRole('menuitem', { name: units.length === 1 ? `Domande sull'unità ${units[0]}` : `Domande sulle unità ${units[0]}–${units.at(-1)}` })).toBeInTheDocument()
  const review = screen.getByRole('menuitem', { name: /Verifica questa parte/ })
  expect(review).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(review)
  expect(run).not.toHaveBeenCalled()
  expect(screen.queryByTestId('document-menu-part')).not.toBeInTheDocument()
  expect(screen.queryByTestId('part-review')).not.toBeInTheDocument()
})
