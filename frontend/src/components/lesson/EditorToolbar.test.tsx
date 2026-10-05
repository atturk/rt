import { history } from '@codemirror/commands'
import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { EditorToolbar } from './EditorToolbar'
import { timecodeLock } from './timecodeLock'

Range.prototype.getClientRects = () => [] as unknown as DOMRectList
Range.prototype.getBoundingClientRect = () => ({ x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0, toJSON: () => {} } as DOMRect)
const views: EditorView[] = []
function createView(doc: string, readOnly = false) {
  const view = new EditorView({ parent: document.body, state: EditorState.create({ doc, extensions: [markdown({ base: markdownLanguage }), history(), timecodeLock, EditorState.readOnly.of(readOnly)] }) })
  views.push(view)
  return view
}
afterEach(() => { cleanup(); views.splice(0).forEach(view => view.destroy()) })
it('usa il comando del registro sul testo selezionato, conserva il focus e annulla/ripete', () => {
  const view = createView('testo')
  view.dispatch({ selection: { anchor: 0, head: 5 } })
  const component = () => <EditorToolbar view={view} state={view.state} shortcuts={{ bold: 'Mod-Shift-j' }} readOnly={false} />
  const ui = render(component())
  const bold = screen.getByRole('button', { name: 'Grassetto (Ctrl+Shift+J)' })
  fireEvent.mouseDown(bold)
  fireEvent.click(bold)
  expect(view.state.doc.toString()).toBe('**testo**')
  expect(view.hasFocus).toBe(true)
  ui.rerender(component())
  expect(bold).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Annulla (Ctrl+Z)' }))
  expect(view.state.doc.toString()).toBe('testo')
  ui.rerender(component())
  fireEvent.click(screen.getByRole('button', { name: 'Ripeti (Ctrl+Shift+Z)' }))
  expect(view.state.doc.toString()).toBe('**testo**')
})
it('mostra attiva la formattazione che contiene il cursore e la toglie al clic', () => {
  const view = createView('**due parole**')
  view.dispatch({ selection: { anchor: 7 } })
  const ui = render(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  const bold = screen.getByRole('button', { name: 'Grassetto (Ctrl+B)' })
  expect(bold).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(bold)
  expect(view.state.doc.toString()).toBe('due parole')
  ui.rerender(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  expect(bold).toHaveAttribute('aria-pressed', 'false')
  expect(screen.queryByRole('button', { name: /Titolo/ })).toBeNull()
})
it('elenco puntato e numerato cambiano e ripristinano le righe selezionate', () => {
  const view = createView('primo\nsecondo')
  view.dispatch({ selection: { anchor: 0, head: view.state.doc.length } })
  const ui = render(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Elenco puntato' }))
  expect(view.state.doc.toString()).toBe('- primo\n- secondo')
  ui.rerender(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  expect(screen.getByRole('button', { name: 'Elenco puntato' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Elenco numerato' }))
  expect(view.state.doc.toString()).toBe('1. primo\n2. secondo')
  fireEvent.click(screen.getByRole('button', { name: 'Elenco numerato' }))
  expect(view.state.doc.toString()).toBe('primo\nsecondo')
})
it.each(['![immagine](media/foto.png)', '| colonna |', '### 1.1 Unità\n\n00:03\n\nTesto'])('non modifica il blocco protetto %s', doc => {
  const view = createView(doc)
  view.dispatch({ selection: { anchor: doc.includes('00:03') ? doc.indexOf('00:03') + 1 : 2 } })
  render(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  for (const name of ['Grassetto (Ctrl+B)', 'Elenco puntato', 'Elenco numerato', 'Casella (Ctrl+↵)']) fireEvent.click(screen.getByRole('button', { name }))
  expect(view.state.doc.toString()).toBe(doc)
})
it('in sola lettura non mostra la barra', () => {
  const view = createView('testo', true)
  const ui = render(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  expect(screen.queryByRole('toolbar')).toBeNull()
  ui.rerender(<EditorToolbar view={null} shortcuts={{}} readOnly />)
  expect(screen.queryByRole('toolbar')).toBeNull()
})
it('segnala attivo il grassetto della selezione dentro un paragrafo', () => {
  const view = createView('[MOCK] Correzione scientifica proposta #1')
  view.dispatch({ selection: { anchor: 7, head: view.state.doc.length } })
  const ui = render(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  const bold = screen.getByRole('button', { name: 'Grassetto (Ctrl+B)' })
  fireEvent.click(bold)
  ui.rerender(<EditorToolbar view={view} shortcuts={{}} readOnly={false} />)
  expect(bold).toHaveAttribute('aria-pressed', 'true')
})
