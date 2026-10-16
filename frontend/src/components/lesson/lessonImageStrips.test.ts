import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { describe, expect, it } from 'vitest'
import { findMarkdownImageStrips, lessonImageStrips } from './lessonImageStrips'

describe('lessonImageStrips', () => {
  it('trova blocchi di 2 o più immagini consecutive nel testo markdown', () => {
    const text = [
      '### 1.1 Unità',
      '00:00',
      '',
      '![Doc.pdf, pagina 1](assets/images/img1.png)',
      '',
      '![Doc.pdf, pagina 2](assets/images/img2.png)',
      '',
      'Testo normale.',
      '',
      '![Singola](assets/images/single.png)',
      '',
      'Altro testo.',
    ].join('\n')

    const state = EditorState.create({ doc: text })
    const strips = findMarkdownImageStrips(state, 1)

    expect(strips).toHaveLength(1)
    expect(strips[0].images).toHaveLength(2)
    expect(strips[0].images[0].docName).toBe('Doc.pdf')
    expect(strips[0].images[0].pageNumber).toBe(1)
    expect(strips[0].images[1].pageNumber).toBe(2)
  })

  it('mostra il widget della striscia quando la selezione è fuori, e mostra il testo quando il cursore entra', () => {
    const text = [
      '### 1.1 Unità',
      '![Doc.pdf, pagina 1](assets/images/img1.png)',
      '![Doc.pdf, pagina 2](assets/images/img2.png)',
      'Testo successivo.',
    ].join('\n')

    const parent = document.createElement('div')
    document.body.append(parent)

    // Cursore su "Testo successivo." (fuori dalla striscia)
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: text,
        selection: { anchor: text.indexOf('Testo successivo.') },
        extensions: [lessonImageStrips(1)],
      }),
    })

    // La striscia è montata nel DOM di CodeMirror
    expect(parent.querySelector('.rt-strip')).not.toBeNull()

    // Sposta il cursore sulla prima riga dell'immagine (dentro la striscia)
    view.dispatch({
      selection: { anchor: text.indexOf('![Doc.pdf, pagina 1]') + 2 },
    })

    // Le righe markdown compaiono come testo (il widget è tolto per permettere la modifica)
    expect(parent.querySelector('.rt-strip')).toBeNull()

    view.destroy()
    parent.remove()
  })
})
