import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { lessonImageStrips } from './lessonImageStrips'
import { lessonImages, lessonUnits, setLinkedUnit, setUnitTasks, unitRanges } from './lessonUnits'
import { timecodeLock } from './timecodeLock'

it('affianca gli stati ai titoli e lo scheletro all’unità corrente senza modificare il Markdown', () => {
  const markdown = '## 1. Sezione\n### 1.1 Prima\n00:00\nTesto.\n### 1.2 Seconda\n\n### 1.3 Terza'
  const parent = document.createElement('div')
  const view = new EditorView({ parent, state: EditorState.create({ doc: markdown, extensions: [lessonUnits, timecodeLock] }) })
  view.dispatch({ effects: setUnitTasks.of(Object.fromEntries((['done', 'working', 'waiting'] as const).map((state, i) => {
    const element = document.createElement('span'); element.textContent = state
    return [`1.${i + 1}`, { state, element }]
  }))) })
  expect(parent.querySelector('[data-task="done"]')).toHaveTextContent('done')
  expect(parent.querySelector('[data-task="working"]')).toHaveTextContent('working')
  expect(parent.querySelector('.rt-unit-waiting')).toHaveTextContent('Terza')
  expect(parent.querySelectorAll('.rt-unit-pending > div')).toHaveLength(3)
  expect(parent.querySelector('.rt-timecode')).toHaveTextContent('00:00')
  expect(view.state.doc.toString()).toBe(markdown)
  view.dispatch({ effects: setUnitTasks.of({}) })
  expect(parent.querySelector('.rt-unit-pending')).toBeNull()
  expect(parent.querySelector('[data-task]')).toBeNull()
  view.destroy()
})

it('un titolo senza numero dentro un\'unità non la chiude (come per il server)', () => {
  const doc = '## 1. Sezione\n\n### 1.1 Prima\n\n00:00\n\nTesto.\n\n### Approfondimento\n\nAncora 1.1.\n\n### 1.2 Seconda\n\n00:10\n\nAltro.'
  const ranges = unitRanges(EditorState.create({ doc }))
  expect(ranges.map((r) => r.id)).toEqual(['1.1', '1.2'])
  expect(doc.slice(ranges[0].from, ranges[0].to)).toContain('Ancora 1.1.')
})

it('segna l’unità raggiunta dal link e toglie il segno cambiando destinazione', () => {
  const doc = '### 1.1 Prima\nTesto.\n### 1.2 Seconda\nAltro.'
  const parent = document.createElement('div')
  const view = new EditorView({ parent, state: EditorState.create({ doc, extensions: [lessonUnits] }) })
  view.dispatch({ effects: setLinkedUnit.of('1.2') })
  expect(parent.querySelector('[data-unit-id="1.2"]')).toHaveClass('rt-claim-unit')
  expect(parent.querySelector('[data-unit-id="1.1"]')).not.toHaveClass('rt-claim-unit')
  view.dispatch({ effects: setLinkedUnit.of(null) })
  expect(parent.querySelector('.rt-claim-unit')).toBeNull()
  expect(view.state.doc.toString()).toBe(doc)
  view.destroy()
})

it('le immagini con didascalia con parentesi [ ] e #w= applicano la larghezza; il clic seleziona o apre il visore', () => {
  const doc = '### 1.1 Prima\n00:00\n![[MOCK] Didascalia](assets/images/foto.png#w=320)\nTesto.'
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: [lessonImageStrips(1), lessonImages(1)],
      selection: { anchor: doc.length },
    }),
  })

  const img = parent.querySelector('.rt-editor-image img') as HTMLImageElement
  expect(img).toBeInTheDocument()
  expect(img.style.width).toBe('320px')

  // 1. Con il pannello aperto
  const panel = document.createElement('div')
  panel.setAttribute('data-testid', 'enrichment-panel')
  document.body.appendChild(panel)

  const selectListener = vi.fn()
  const viewerListener = vi.fn()
  window.addEventListener('rt-media-select', selectListener)
  window.addEventListener('rt-image-viewer-open', viewerListener)

  img.click()

  expect(selectListener).toHaveBeenCalledWith(
    expect.objectContaining({ detail: { name: 'foto.png' } }),
  )
  expect(viewerListener).not.toHaveBeenCalled()

  // 2. Con il pannello chiuso
  panel.remove()
  selectListener.mockClear()
  viewerListener.mockClear()

  img.click()

  expect(selectListener).not.toHaveBeenCalled()
  expect(viewerListener).toHaveBeenCalledWith(
    expect.objectContaining({ detail: { index: 0, images: expect.arrayContaining([expect.objectContaining({ src: '/api/v1/lessons/1/assets/images/foto.png' })]) } }),
  )

  window.removeEventListener('rt-media-select', selectListener)
  window.removeEventListener('rt-image-viewer-open', viewerListener)
  view.destroy()
  parent.remove()
})
