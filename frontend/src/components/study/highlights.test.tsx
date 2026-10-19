import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { UnitText } from './Study'
import { useStudyHighlighter, type HighlightMode } from './highlights'
import { sourceRange, sourceTextOf } from '@/lib/sourceText'

const api = vi.hoisted(() => ({ list: vi.fn(async () => [] as unknown[]), add: vi.fn(async (_lessonId: number, _body: Record<string, unknown>) => ({ id: 7 })), remove: vi.fn(async () => {}), clear: vi.fn(async () => {}) }))
vi.mock('@/api/highlights', () => ({ highlightsApi: api }))
const source = 'Prima $D$ dopo e fine.'
const unit = { id: '1.1', title: 'Test', html: `<p>${source}</p>`, questions: 0, pending: {}, status: 'da-imparare' as const }
function Harness({ mode = 'evidenzia' }: { mode?: HighlightMode }) {
  const [root, setRoot] = useState<HTMLElement | null>(null)
  const { clear } = useStudyHighlighter({ root, lessonId: 1, unitId: '1.1', mode, color: 2 })
  return <><UnitText lessonId={1} unit={unit} highlightMode={mode} onReady={setRoot} /><button onClick={clear}>Pulisci</button></>
}
beforeEach(() => { vi.clearAllMocks(); api.list.mockResolvedValue([]) })

it.each([[0, source.length], [6, 9], [6, source.length], [0, 9]])('evidenzia, ricarica e cancella anche formule sole (%s…%s)', async (start, end) => {
  const view = render(<Harness />)
  await waitFor(() => expect(api.list).toHaveBeenCalled())
  let root = screen.getByTestId('study-text')
  await act(async () => {
    const selection = window.getSelection()!
    selection.removeAllRanges(); selection.addRange(sourceRange(root, start, end)!)
    fireEvent.mouseUp(root, { button: 0 })
  })
  expect(api.add).toHaveBeenCalledTimes(1)
  expect(api.add.mock.calls[0]).toEqual([1, expect.objectContaining({ color: 2, source: expect.objectContaining({ text: source.slice(start, end) }) })])
  expect(root.querySelector('math .rt-hl')).toBeNull()
  expect(root.querySelector('math')!.classList.contains('rt-hl-math')).toBe(true)
  expect(root.querySelector('math')!.classList.contains('rt-hl-2')).toBe(true)
  expect(sourceTextOf(root)).toBe(source)
  const body = api.add.mock.calls[0][1]
  api.list.mockResolvedValue([{ ...body, id: 7 }])
  view.unmount()
  const reloaded = render(<Harness mode="gomma" />)
  root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelector('math')?.classList.contains('rt-hl-math')).toBe(true))
  fireEvent.mouseUp(root.querySelector('math')!, { button: 0 })
  await waitFor(() => expect(api.remove).toHaveBeenCalledWith(1, 7))
  expect(root.querySelector('math')!.classList.contains('rt-hl-math')).toBe(false)
  reloaded.unmount()
})

it('Pulisci toglie anche i colori applicati soltanto alle formule', async () => {
  api.list.mockResolvedValue([{ id: 7, color: 1, source: { id: 'formula', text: '$D$', sourceStart: 6, sourceEnd: 9, startMeta: { parentIndex: -2 }, endMeta: { parentIndex: -2 } } }])
  render(<Harness />)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelector('math')?.classList.contains('rt-hl-math')).toBe(true))
  fireEvent.click(screen.getByText('Pulisci'))
  await waitFor(() => expect(api.clear).toHaveBeenCalledWith(1, '1.1'))
  expect(root.querySelector('math')!.classList.contains('rt-hl-math')).toBe(false)
})


it('evidenzia una formula anche su HTTP senza crypto.randomUUID', async () => {
  vi.stubGlobal('crypto', {})
  try {
    render(<Harness />)
    await waitFor(() => expect(api.list).toHaveBeenCalled())
    const root = screen.getByTestId('study-text')
    await act(async () => {
      const selection = window.getSelection()!
      selection.removeAllRanges(); selection.addRange(sourceRange(root, 6, 9)!)
      fireEvent.mouseUp(root, { button: 0 })
    })
    expect(api.add).toHaveBeenCalledWith(1, expect.objectContaining({ source: expect.objectContaining({ text: '$D$', id: expect.stringMatching(/^rt-math-/) }) }))
    expect(root.querySelector('math')!.classList.contains('rt-hl-math')).toBe(true)
  } finally { vi.unstubAllGlobals() }
})

it('ritrova le evidenziazioni salvate prima del LaTeX accanto alle formule', async () => {
  api.list.mockImplementation(async () => {
    // Posizione come la calcolava web-highlighter senza lo span del sorgente.
    const clone = screen.getByTestId('study-text').querySelector('p')!.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.rt-math-src').forEach(raw => raw.remove())
    const start = clone.textContent!.indexOf('dopo')
    const meta = (offset: number) => ({ parentTagName: 'P', parentIndex: 0, textOffset: offset })
    return [{ id: 7, color: 1, source: { id: 'vecchia', text: 'dopo', startMeta: meta(start), endMeta: meta(start + 4) } }]
  })
  render(<Harness />)
  const root = screen.getByTestId('study-text')
  await waitFor(() => expect(root.querySelector('.rt-hl-1')?.textContent).toBe('dopo'))
  expect(root.querySelector('math')!.nextElementSibling?.matches('.rt-math-src')).toBe(true)
  expect(sourceTextOf(root)).toBe(source)
})
