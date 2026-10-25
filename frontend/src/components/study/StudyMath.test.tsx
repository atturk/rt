import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { UnitText } from './Study'
import { sourceRange, sourceTextOf } from '@/lib/sourceText'
import { readUnitWords } from './rsvp'
import type { StudyNote } from '@/api/studyNotes'

const source = String.raw`Il dominio $D$ contiene $(x, y, z)$ e $\underline{R}_{12}$, con grassetto.`
const unit = { id: '1.1', title: 'Formule', html: `<p>${source.replace('grassetto', '<strong>grassetto</strong>')}</p>`, questions: 0, pending: {}, status: 'da-imparare' as const }

function select(root: HTMLElement, start = 0, end = source.length) {
  const selection = window.getSelection()!
  const range = sourceRange(root, start, end)!
  range.getBoundingClientRect = () => new DOMRect(10, 10, 100, 20)
  selection.removeAllRanges(); selection.addRange(range)
  fireEvent(document, new Event('selectionchange'))
}

it('copia il LaTeX con evidenziatore spento e lo mostra soltanto durante la selezione', async () => {
  render(<UnitText lessonId={1} unit={unit} highlightMode={null} onReady={vi.fn()} />)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelectorAll('.rt-math-src')).toHaveLength(3))
  select(root)
  await waitFor(() => expect(root.querySelectorAll('math.rt-math-raw')).toHaveLength(3))
  const setData = vi.fn()
  fireEvent.copy(root, { clipboardData: { setData } })
  expect(setData).toHaveBeenCalledWith('text/plain', source)
  const words = readUnitWords(root).words
  expect(words.filter(w => w.math)).toHaveLength(3)
  expect(words.filter(w => w.math).every(w => !w.math!.html.includes('rt-math-raw'))).toBe(true)
  expect(words.some(w => w.text.includes('$'))).toBe(false)
  window.getSelection()!.removeAllRanges(); fireEvent(document, new Event('selectionchange'))
  await waitFor(() => expect(root.querySelector('.rt-math-raw')).toBeNull())
})

it.each(['verifica', 'chiedi'] as const)('%s riceve citazione e contesto sorgente dopo una evidenziazione', async mode => {
  const onSelection = vi.fn()
  render(<UnitText lessonId={1} unit={unit} highlightMode={mode} onReady={vi.fn()} onSelection={onSelection} />)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelectorAll('.rt-math-src')).toHaveLength(3))
  const paragraph = root.querySelector('p')!
  const mark = document.createElement('span'); mark.className = 'rt-hl rt-hl-0'
  paragraph.insertBefore(mark, paragraph.firstChild); mark.append(mark.nextSibling!)
  select(root, 3, source.indexOf(', con'))
  fireEvent.mouseUp(root)
  const quote = source.slice(3, source.indexOf(', con'))
  expect(onSelection).toHaveBeenCalledWith(quote, { quote, prefix: 'Il ', suffix: ', con grassetto.', start: 3, end: source.indexOf(', con') }, expect.anything())
  expect(sourceTextOf(root)).toBe(source)
})

it('segna, apre dalla formula e pulisce una nota attraverso formule e grassetto senza toccare il MathML', async () => {
  const notes = [{ id: 1, kind: 'chiedi', anchor_state: 'trovata', current_quote: source }] as StudyNote[]
  const onReady = vi.fn(), onNoteClick = vi.fn()
  const view = render(<UnitText lessonId={1} unit={unit} highlightMode={null} onReady={onReady} notes={notes} activeNoteId={1} onNoteClick={onNoteClick} />)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelectorAll('math.rt-sn-math')).toHaveLength(3))
  expect(root.querySelector('strong .rt-sn')).not.toBeNull()
  expect(root.querySelector('math span')).toBeNull()
  fireEvent.click(root.querySelector('math mi')!)
  expect(onNoteClick).toHaveBeenCalledWith(notes[0], expect.anything())
  view.rerender(<UnitText lessonId={1} unit={unit} highlightMode={null} onReady={onReady} notes={notes} activeNoteId={null} />)
  expect(root.querySelector('.rt-sn-math, .rt-sn')).toBeNull()
  expect(sourceTextOf(root)).toBe(source)
})

it('lascia la copia al browser quando la selezione non tocca formule e converte anche con Ctrl+A', async () => {
  render(<div><h2>Titolo</h2><UnitText lessonId={1} unit={unit} highlightMode={null} onReady={vi.fn()} /></div>)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelectorAll('.rt-math-src')).toHaveLength(3))
  select(root, 0, 3)
  const setData = vi.fn()
  fireEvent.copy(root, { clipboardData: { setData } })
  expect(setData).not.toHaveBeenCalled()
  const all = document.createRange(); all.selectNodeContents(document.body)
  window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(all)
  fireEvent(document, new Event('selectionchange'))
  await waitFor(() => expect(root.querySelectorAll('math.rt-math-raw')).toHaveLength(3))
  fireEvent.copy(root, { clipboardData: { setData } })
  expect(setData).toHaveBeenCalledWith('text/plain', source)
})

it('Studio: graffetta, immagini della sezione e immagini nel testo separate', () => {
  const imagesUnit = { ...unit, start_formatted: '00:00', immagini_sezione: ['slide.png'], html: '<p><img src="assets/images/slide.png" alt="Slide.pdf, p. 2"></p><p>Testo</p><p><img src="assets/images/inline.png#w=240" width="240"></p>' }
  const view = render(<UnitText lessonId={1} unit={imagesUnit} highlightMode={null} onReady={vi.fn()} />)
  const button = screen.getByRole('button', { name: 'Mostra le immagini · M' })
  expect(button).toHaveTextContent('1')
  expect(button.nextElementSibling).toHaveTextContent('00:00')
  fireEvent.click(button)
  expect(view.container.querySelector<HTMLElement>('.rt-unit-images-section')!.hidden).toBe(false)
  expect(view.container.querySelectorAll('.rt-unit-images-section .thumb')).toHaveLength(1)
  expect(view.container.querySelector('p img[width="240"]')).toBeInTheDocument()
})
