import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { afterEach, describe, expect, it } from 'vitest'

import {
  deleteLineOrParagraph,
  indentLessLines,
  indentMoreLines,
  markdownShortcuts,
  toggleBold,
  toggleCheckbox,
  toggleHighlight,
  toggleInlineCode,
  toggleItalic,
  toggleLink,
  toggleStrikethrough,
} from './markdownShortcuts'
import { timecodeLock } from './timecodeLock'

if (typeof Range !== 'undefined') {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => ({
    x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0,
    toJSON: () => {},
  } as DOMRect)
}

const views: EditorView[] = []

function createView(doc: string, options: { readOnly?: boolean; extensions?: any[] } = {}) {
  const extensions = [
    markdownShortcuts,
    timecodeLock,
    ...(options.readOnly ? [EditorState.readOnly.of(true)] : []),
    ...(options.extensions ?? []),
  ]
  const state = EditorState.create({ doc, extensions })
  const view = new EditorView({ state })
  views.push(view)
  return view
}

afterEach(() => {
  while (views.length > 0) {
    views.pop()?.destroy()
  }
})

describe('markdownShortcuts - Grassetto e Corsivo (Mod-b, Mod-i)', () => {
  it('avvolge la selezione con **', () => {
    const view = createView('testo di prova')
    view.dispatch({ selection: { anchor: 0, head: 5 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe('**testo** di prova')
  })

  it('toglie ** se la selezione è già avvolta', () => {
    const view = createView('**testo** di prova')
    view.dispatch({ selection: { anchor: 0, head: 9 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe('testo di prova')
  })

  it('toglie ** se la parola selezionata è avvolta esternamente', () => {
    const view = createView('**testo** di prova')
    view.dispatch({ selection: { anchor: 2, head: 7 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe('testo di prova')
  })

  it('senza selezione dentro una parola, avvolge la parola come Obsidian', () => {
    const view = createView('testo di prova')
    view.dispatch({ selection: { anchor: 2, head: 2 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe('**testo** di prova')
  })

  it('senza selezione dentro una parola già avvolta, toglie i delimitatori', () => {
    const view = createView('**testo** di prova')
    view.dispatch({ selection: { anchor: 4, head: 4 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe('testo di prova')
  })

  it('senza selezione in uno spazio vuoto, inserisce la coppia con il cursore in mezzo', () => {
    const view = createView('   ')
    view.dispatch({ selection: { anchor: 1, head: 1 } })
    const res = toggleBold(view)
    expect(res).toBe(true)
    expect(view.state.doc.toString()).toBe(' ****  ')
    expect(view.state.selection.main.head).toBe(3)
  })

  it('corsivo con Mod-i e non toglie ** di un grassetto', () => {
    const view = createView('testo di prova')
    view.dispatch({ selection: { anchor: 0, head: 5 } })
    toggleItalic(view)
    expect(view.state.doc.toString()).toBe('*testo* di prova')
    toggleItalic(view)
    expect(view.state.doc.toString()).toBe('testo di prova')

    const boldView = createView('**grassetto**')
    boldView.dispatch({ selection: { anchor: 2, head: 11 } })
    toggleItalic(boldView)
    // Non toglie ** perché è grassetto, bensì avvolge in corsivo
    expect(boldView.state.doc.toString()).toBe('***grassetto***')
  })
})

describe('markdownShortcuts - Barrato, Codice ed Evidenziato', () => {
  it('barrato con Mod-Shift-x (~~)', () => {
    const view = createView('cancellato')
    view.dispatch({ selection: { anchor: 0, head: 10 } })
    toggleStrikethrough(view)
    expect(view.state.doc.toString()).toBe('~~cancellato~~')
    toggleStrikethrough(view)
    expect(view.state.doc.toString()).toBe('cancellato')
  })

  it('codice inline con Mod-Shift-c (`)', () => {
    const view = createView('const x = 1')
    view.dispatch({ selection: { anchor: 0, head: 11 } })
    toggleInlineCode(view)
    expect(view.state.doc.toString()).toBe('`const x = 1`')
    toggleInlineCode(view)
    expect(view.state.doc.toString()).toBe('const x = 1')
  })

  it('evidenziato con Mod-Shift-h (==)', () => {
    const view = createView('importante')
    view.dispatch({ selection: { anchor: 0, head: 10 } })
    toggleHighlight(view)
    expect(view.state.doc.toString()).toBe('==importante==')
    toggleHighlight(view)
    expect(view.state.doc.toString()).toBe('importante')
  })
})

describe('markdownShortcuts - Link (Mod-k)', () => {
  it('avvolge testo in [testo]() con il cursore tra le parentesi tonde', () => {
    const view = createView('visita Google adesso')
    view.dispatch({ selection: { anchor: 7, head: 13 } })
    toggleLink(view)
    expect(view.state.doc.toString()).toBe('visita [Google]() adesso')
    expect(view.state.selection.main.head).toBe(16) // tra ( e )
  })

  it('avvolge un URL in [](url) con il cursore tra le quadre', () => {
    const view = createView('visita https://google.com adesso')
    view.dispatch({ selection: { anchor: 7, head: 25 } })
    toggleLink(view)
    expect(view.state.doc.toString()).toBe('visita [](https://google.com) adesso')
    expect(view.state.selection.main.head).toBe(8) // tra [ e ]
  })

  it('senza selezione inserisce []() con cursore tra le quadre', () => {
    const view = createView('')
    toggleLink(view)
    expect(view.state.doc.toString()).toBe('[]()')
    expect(view.state.selection.main.head).toBe(1)
  })
})

describe('markdownShortcuts - Casella di spunta (Mod-Enter)', () => {
  it('aggiunge la spunta se non c’è casella', () => {
    const view = createView('- elemento')
    view.dispatch({ selection: { anchor: 3, head: 3 } })
    toggleCheckbox(view)
    expect(view.state.doc.toString()).toBe('- [ ] elemento')
  })

  it('spunta una casella vuota', () => {
    const view = createView('- [ ] da fare')
    view.dispatch({ selection: { anchor: 6, head: 6 } })
    toggleCheckbox(view)
    expect(view.state.doc.toString()).toBe('- [x] da fare')
  })

  it('despunta una casella spuntata', () => {
    const view = createView('- [x] completato')
    view.dispatch({ selection: { anchor: 6, head: 6 } })
    toggleCheckbox(view)
    expect(view.state.doc.toString()).toBe('- [ ] completato')
  })

  it('su riga senza elenco aggiunge - [ ]', () => {
    const view = createView('compito')
    view.dispatch({ selection: { anchor: 2, head: 2 } })
    toggleCheckbox(view)
    expect(view.state.doc.toString()).toBe('- [ ] compito')
  })
})

describe('markdownShortcuts - Rientro (Mod-] e Mod-[)', () => {
  it('aumenta e riduce il rientro', () => {
    const view = createView('riga uno\nriga due')
    view.dispatch({ selection: { anchor: 0, head: 12 } })
    indentMoreLines(view)
    expect(view.state.doc.toString()).toBe('  riga uno\n  riga due')
    indentLessLines(view)
    expect(view.state.doc.toString()).toBe('riga uno\nriga due')
  })
})

describe('markdownShortcuts - Elimina paragrafo/riga (Mod-d)', () => {
  it('elimina la riga corrente e il suo a capo', () => {
    const view = createView('prima riga\nseconda riga\nterza riga')
    view.dispatch({ selection: { anchor: 15, head: 15 } })
    deleteLineOrParagraph(view)
    expect(view.state.doc.toString()).toBe('prima riga\nterza riga')
  })
})

describe('markdownShortcuts - Protezioni e anteprima di RT (il tasto si consuma senza modifiche)', () => {
  const DOC_WITH_LOCK = '### 1.1 Unità\n\n12:30\n\nTesto normale sotto.\n\n![Foto](assets/images/fig1.png)\n\n| Col A | Col B |\n| --- | --- |\n'

  it('non fa modifiche dentro un timecode bloccato', () => {
    const view = createView(DOC_WITH_LOCK)
    const pos = DOC_WITH_LOCK.indexOf('12:30') + 1
    view.dispatch({ selection: { anchor: pos, head: pos } })

    expect(toggleBold(view)).toBe(true)
    expect(toggleItalic(view)).toBe(true)
    expect(toggleLink(view)).toBe(true)
    expect(toggleCheckbox(view)).toBe(true)
    expect(deleteLineOrParagraph(view)).toBe(true)
    expect(view.state.doc.toString()).toBe(DOC_WITH_LOCK)
  })

  it('non fa modifiche dentro un blocco immagine', () => {
    const view = createView(DOC_WITH_LOCK)
    const pos = DOC_WITH_LOCK.indexOf('assets/images')
    view.dispatch({ selection: { anchor: pos, head: pos } })

    expect(toggleBold(view)).toBe(true)
    expect(toggleCheckbox(view)).toBe(true)
    expect(view.state.doc.toString()).toBe(DOC_WITH_LOCK)
  })

  it('non fa modifiche dentro una tabella', () => {
    const view = createView(DOC_WITH_LOCK)
    const pos = DOC_WITH_LOCK.indexOf('Col A')
    view.dispatch({ selection: { anchor: pos, head: pos } })

    expect(toggleBold(view)).toBe(true)
    expect(toggleCheckbox(view)).toBe(true)
    expect(view.state.doc.toString()).toBe(DOC_WITH_LOCK)
  })

  it('in sola lettura (readOnly) non fa niente', () => {
    const view = createView('testo in sola lettura', { readOnly: true })
    view.dispatch({ selection: { anchor: 0, head: 5 } })

    expect(toggleBold(view)).toBe(true)
    expect(toggleItalic(view)).toBe(true)
    expect(toggleLink(view)).toBe(true)
    expect(toggleCheckbox(view)).toBe(true)
    expect(indentMoreLines(view)).toBe(true)
    expect(deleteLineOrParagraph(view)).toBe(true)
    expect(view.state.doc.toString()).toBe('testo in sola lettura')
  })
})
