import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { describe, expect, it } from 'vitest'

import { loadTemml } from '@/lib/math'

import { lessonMath, mathRanges } from './lessonMath'

const ranges = (text: string) => mathRanges(EditorState.create({ doc: text }))

/** L'editor con l'estensione, dopo che Temml si è caricato. */
async function editor(doc: string, cursor?: number) {
  const view = new EditorView({
    state: EditorState.create({ doc, extensions: [lessonMath], selection: cursor === undefined ? undefined : { anchor: cursor } }),
    parent: document.body,
  })
  await loadTemml()
  for (let i = 0; i < 20 && !view.dom.querySelector('.rt-editor-math'); i++) await new Promise((resolve) => setTimeout(resolve, 5))
  return view
}

describe('formule nell’editor', () => {
  it('trova le formule e distingue quelle che stanno su una riga da sole', () => {
    const found = ranges('Testo $x^2$ e poi\n$$a = b$$\nfine.')
    expect(found.map((m) => [m.source, m.display, m.block])).toEqual([['x^2', false, false], ['a = b', true, true]])
  })

  it('salta i blocchi di codice e il codice in riga', () => {
    expect(ranges('```\n$x^2$\n```\n')).toEqual([])
    expect(ranges('prezzi in `$x$` e testo')).toEqual([])
    expect(ranges('costa 5$ e 10$, da $5 a $10')).toEqual([])
  })

  it('rende la formula e rimette il LaTeX quando il cursore ci entra', async () => {
    const view = await editor('Il campo $$E = 3$$ qui.')
    expect(view.dom.querySelector('.rt-editor-math math')).not.toBeNull()
    expect(view.dom.textContent).not.toContain('$$E = 3$$')
    view.dispatch({ selection: { anchor: 12 } })
    expect(view.dom.querySelector('.rt-editor-math')).toBeNull()
    expect(view.dom.textContent).toContain('$$E = 3$$')
    view.destroy()
  })

  it('senza formule non disegna niente', async () => {
    const view = await editor('Solo testo, nessuna formula.')
    expect(view.dom.querySelector('.rt-editor-math')).toBeNull()
    view.destroy()
  })
})
