import { EditorState, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view'
import { beforeEach, describe, expect, it } from 'vitest'
import { findMarkdownImageStrips, lessonImageStrips, toggleUnitImages } from './lessonImageStrips'

const nodeFs = (globalThis as unknown as { process?: { getBuiltinModule?: (id: string) => { readFileSync: (path: string, encoding: string) => string } } }).process?.getBuiltinModule?.('node:fs')
const cssContent = nodeFs ? nodeFs.readFileSync('src/index.css', 'utf-8') : ''
const ruleMatch = cssContent.match(/(\.rt-unit-images-section\s*\+\s*\.cm-atomic-image[^{]*\{[^}]*\})/)

const text = '### 1.1 Unità\n00:00\n\n![Doc.pdf, pagina 1](assets/images/img1.png)\n\n![Doc.pdf, pagina 2](assets/images/img2.png)\n\nTesto normale.\n\n![Singola](assets/images/single.png)'
describe('lessonImageStrips', () => {
  beforeEach(() => {
    const style = document.createElement('style')
    style.textContent = ruleMatch ? ruleMatch[1] : '.rt-unit-images-section + .cm-atomic-image { display: none !important; }'
    document.head.append(style)
  })
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
  it('nelle sezioni (## N.) il bottone sta in una riga sotto il titolo', () => {
    const parent = document.createElement('div')
    const doc = '## 7. Entropia\n![Doc.pdf, pagina 1](assets/images/img1.png)\n\nTesto'
    const view = new EditorView({ parent, state: EditorState.create({ doc, extensions: [lessonImageStrips(1)] }) })
    const row = parent.querySelector<HTMLElement>('.rt-unit-images-row')!
    expect(row.querySelector('.rt-unit-images-button')!.textContent).toBe('1')
    expect(row.closest('.cm-line')).toBeNull()
    view.destroy()
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
  it('sezione con due immagini: nessuna cm-atomic-image visibile per quei file sia con sezione chiusa che aperta', () => {
    class MockAtomicImageWidget extends WidgetType {
      readonly src: string
      constructor(src: string) {
        super()
        this.src = src
      }
      toDOM() {
        const wrap = document.createElement('div')
        wrap.className = 'cm-atomic-image'
        wrap.dataset.src = this.src
        const img = document.createElement('img')
        img.src = this.src
        wrap.append(img)
        return wrap
      }
    }

    const mockImageBlocks = StateField.define<DecorationSet>({
      create(state) {
        const ranges: any[] = []
        for (let i = 1; i <= state.doc.lines; i++) {
          const line = state.doc.line(i)
          const match = line.text.match(/!\[([^\]]*)\]\(([^)\s]+)\)/)
          if (match) {
            ranges.push(Decoration.widget({ widget: new MockAtomicImageWidget(match[2]), block: true, side: 1 }).range(line.to))
          }
        }
        return Decoration.set(ranges, true)
      },
      update(deco) { return deco },
      provide: f => EditorView.decorations.from(f),
    })

    const parent = document.createElement('div')
    document.body.append(parent)
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: text,
        extensions: [mockImageBlocks, lessonImageStrips(1)],
      }),
    })

    // Sezione chiusa di default:
    let section = parent.querySelector('.rt-unit-images-section')!
    expect(section).not.toBeNull()
    expect(section).toHaveClass('closed')

    if (cssContent) {
      expect(cssContent).toMatch(/\.rt-unit-images-section\s*\+\s*\.cm-atomic-image/)
      expect(cssContent).not.toContain('.cm-content > .rt-strip + .cm-atomic-image')
    }

    let atomicImages = Array.from(parent.querySelectorAll<HTMLElement>('.cm-atomic-image'))
    for (const el of atomicImages) {
      if (el.dataset.src === 'assets/images/img1.png' || el.dataset.src === 'assets/images/img2.png') {
        expect(window.getComputedStyle(el).display).toBe('none')
      }
    }

    // Apriamo la sezione
    const button = parent.querySelector<HTMLButtonElement>('.rt-unit-images-button')!
    button.click()
    section = parent.querySelector('.rt-unit-images-section')!
    expect(section).not.toHaveClass('closed')

    atomicImages = Array.from(parent.querySelectorAll<HTMLElement>('.cm-atomic-image'))
    for (const el of atomicImages) {
      if (el.dataset.src === 'assets/images/img1.png' || el.dataset.src === 'assets/images/img2.png') {
        expect(window.getComputedStyle(el).display).toBe('none')
      }
    }

    // L'immagine successiva nel testo normale non è nascosta
    const singleEl = atomicImages.find(el => el.dataset.src === 'assets/images/single.png')
    expect(singleEl).toBeDefined()
    expect(window.getComputedStyle(singleEl!).display).not.toBe('none')

    view.destroy()
    parent.remove()
  })
})
