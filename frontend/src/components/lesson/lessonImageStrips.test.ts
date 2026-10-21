import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { describe, expect, it } from 'vitest'
import { findMarkdownImageStrips, lessonImageStrips, toggleUnitImages } from './lessonImageStrips'

const text = '### 1.1 Unità\n00:00\n\n![Doc.pdf, pagina 1](assets/images/img1.png)\n\n![Doc.pdf, pagina 2](assets/images/img2.png)\n\nTesto normale.\n\n![Singola](assets/images/single.png)'
describe('lessonImageStrips', () => {
  it('raggruppa solo le immagini iniziali della sezione', () => {
    const strips = findMarkdownImageStrips(EditorState.create({ doc: text }), 1)
    expect(strips).toHaveLength(1)
    expect(strips[0].images).toHaveLength(2)
    expect(strips[0].images.map(image => image.pageNumber)).toEqual([1, 2])
    expect(strips[0].images[0].docName).toBe('Doc.pdf')
  })
  it('una immagine iniziale con larghezza resta nel testo', () => {
    const doc = text.replace('img1.png)', 'img1.png#w=320)')
    expect(findMarkdownImageStrips(EditorState.create({ doc }), 1)).toHaveLength(0)
  })
  it('bottone con conteggio, apertura locale e blocco atomico anche con cursore dentro', () => {
    const parent = document.createElement('div')
    document.body.append(parent)
    const view = new EditorView({ parent, state: EditorState.create({ doc: text, extensions: [lessonImageStrips(1)] }) })
    const button = parent.querySelector<HTMLButtonElement>('.rt-unit-images-button')!
    expect(button.textContent).toBe('2')
    expect(parent.querySelector('.rt-strip')).toBeNull()
    button.click()
    expect(parent.querySelectorAll('.thumb')).toHaveLength(2)
    view.dispatch({ selection: { anchor: text.indexOf('![Doc') + 2 } })
    expect(parent.querySelector('.rt-strip')).not.toBeNull()
    expect(parent.querySelector('.rt-strip-editing-line')).toBeNull()
    const atomic = view.state.facet(EditorView.atomicRanges)[0](view)
    let found = false
    atomic.between(text.indexOf('![Doc'), text.indexOf('Testo'), () => { found = true })
    expect(found).toBe(true)
    view.dispatch({ effects: toggleUnitImages.of('1.1') })
    expect(parent.querySelector('.rt-strip')).toBeNull()
    expect(view.state.doc.toString()).toBe(text)
    view.destroy(); parent.remove()
  })
  it('sezione vuota: bottone disponibile solo per il trascinamento', () => {
    const parent = document.createElement('div')
    const view = new EditorView({ parent, state: EditorState.create({ doc: '### 1.1 Unità\n00:00\nTesto', extensions: [lessonImageStrips(1)] }) })
    const button = parent.querySelector<HTMLElement>('.rt-unit-images-button')!
    expect(button).toHaveClass('empty')
    expect(button.textContent).toBe('')
    expect(button.dataset.unitImages).toBe('1.1')
    view.destroy()
  })
})
