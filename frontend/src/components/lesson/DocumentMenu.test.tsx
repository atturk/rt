import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { DocumentMenu } from './DocumentMenu'
const run = vi.hoisted(() => vi.fn())
vi.mock('@/api/hooks', () => ({ useRunJob: () => ({ mutateAsync: run }) }))
const job = vi.hoisted(() => ({ data: null as null | { state: string; result?: { issues: number }; error?: string } }))
vi.mock('@/api/jobs', () => ({ useJob: () => ({ data: job.data }) }))
vi.mock('@/api/enrichment', () => ({ useEnrichmentActions: () => ({ generate: {} }) }))
beforeEach(() => { run.mockReset(); run.mockResolvedValue({ job_id: 'parte' }); job.data = null })
const anchor = { quote: 'Testo selezionato', prefix: '', suffix: '', start: 0, end: 17 }
it.each([['1.2'], ['1.2', '1.3']])('dice le unità %j e avvia la verifica contestuale', async (...units: string[]) => {
  const parts = units.map(unit_id => ({ unit_id, anchor }))
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={units} ready locate={() => ({ text: anchor.quote, units, reviewParts: parts, anchor: { x: 0, y: 0 } })}><p>Documento</p></DocumentMenu></MemoryRouter>)
  fireEvent.contextMenu(screen.getByText('Documento'))
  expect(screen.getByRole('menuitem', { name: units.length === 1 ? `Domande sull'unità ${units[0]}` : `Domande sulle unità ${units[0]}–${units.at(-1)}` })).toBeInTheDocument()
  const review = screen.getByRole('menuitem', { name: /Verifica questa parte/ })
  expect(review).not.toHaveAttribute('aria-disabled')
  fireEvent.click(review)
  await waitFor(() => expect(run).toHaveBeenCalledWith({ type: 'review_part', parts }))
  expect(screen.getByTestId('part-review-notice')).toHaveTextContent('Verifica in corso')
  expect(screen.queryByTestId('document-menu-part')).not.toBeInTheDocument()
  expect(screen.queryByTestId('part-review')).not.toBeInTheDocument()
})

it('salva prima di accodare e mostra conteggio e link in basso', async () => {
  const flush = vi.fn(async () => { expect(run).not.toHaveBeenCalled() })
  job.data = { state: 'succeeded', result: { issues: 3 } }
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={['1.2']} ready={false} beforeReview={flush} locate={() => ({ text: anchor.quote, units: ['1.2'], reviewParts: [{ unit_id: '1.2', anchor }], anchor: { x: 0, y: 0 } })}><p>Documento</p></DocumentMenu></MemoryRouter>)
  fireEvent.contextMenu(screen.getByText('Documento'))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Verifica questa parte' }))
  await waitFor(() => expect(run).toHaveBeenCalled())
  expect(flush).toHaveBeenCalledOnce()
  expect(screen.getByTestId('part-review-notice')).toHaveClass('fixed', 'bottom-4')
  expect(screen.getByTestId('part-review-notice')).toHaveTextContent('3 issue trovate')
  expect(screen.getByRole('link', { name: 'Apri Verifica' })).toHaveAttribute('href', '/lezioni/1?panel=verifica&review_unit=1.2')
  fireEvent.click(screen.getByRole('button', { name: 'Chiudi l’avviso di verifica' }))
  expect(screen.queryByTestId('part-review-notice')).not.toBeInTheDocument()
})

it('non accoda se il salvataggio fallisce e mostra l’errore', async () => {
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={['1.2']} ready beforeReview={async () => { throw new Error('Salvataggio fallito') }} locate={() => ({ text: anchor.quote, units: ['1.2'], reviewParts: [{ unit_id: '1.2', anchor }], anchor: { x: 0, y: 0 } })}><p>Documento</p></DocumentMenu></MemoryRouter>)
  fireEvent.contextMenu(screen.getByText('Documento'))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Verifica questa parte' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Salvataggio fallito'))
  expect(run).not.toHaveBeenCalled()
})

it('sui titoli senza selezione mantiene Verifica disattiva', () => {
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={['1.2']} ready locate={() => ({ text: 'Titolo', units: ['1.2'], anchor: { x: 0, y: 0 } })}><p>Documento</p></DocumentMenu></MemoryRouter>)
  fireEvent.contextMenu(screen.getByText('Documento'))
  expect(screen.getByRole('menuitem', { name: 'Verifica questa parte' })).toHaveAttribute('aria-disabled', 'true')
})

it.each([{ button: 2 }, { button: 0, ctrlKey: true }])('senza selezione usa il paragrafo anche con ctrl+clic: %j', (mouse) => {
  vi.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel')
  window.getSelection()?.removeAllRanges()
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={['1.1']} ready><article><h3 data-unit-id="1.1">Test</h3><p>Un intero paragrafo sotto il clic.</p></article></DocumentMenu></MemoryRouter>)
  const paragraph = screen.getByText('Un intero paragrafo sotto il clic.')
  fireEvent.mouseDown(paragraph, mouse)
  // Safari seleziona una parola dopo mousedown: il contesto resta il paragrafo.
  const range = document.createRange()
  range.setStart(paragraph.firstChild!, 3)
  range.setEnd(paragraph.firstChild!, 9)
  window.getSelection()?.addRange(range)
  fireEvent.contextMenu(paragraph, { ctrlKey: mouse.ctrlKey })
  expect(screen.getByRole('menu', { name: 'Azioni sul testo' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: "Domande sull'unità 1.1" })).toBeInTheDocument()
  expect(screen.getByText('⌥ + clic destro: menu del browser')).toBeInTheDocument()
  window.getSelection()?.removeAllRanges()
})

it('con ⌥ lascia il menu del browser anche se una superficie editor sa localizzare il testo', () => {
  const locate = vi.fn(() => ({ text: 'Testo', units: ['1.1'], anchor: { x: 0, y: 0 } }))
  render(<MemoryRouter><DocumentMenu lessonId={1} unitIds={['1.1']} ready locate={locate}><p>Documento</p></DocumentMenu></MemoryRouter>)
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, altKey: true })
  fireEvent(screen.getByText('Documento'), event)
  expect(event.defaultPrevented).toBe(false)
  expect(locate).not.toHaveBeenCalled()
  expect(screen.queryByRole('menu')).toBeNull()
})
