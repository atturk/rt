import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { unmountDomTooltip } from '@/components/ui/dom-tooltip'
import { lessonShortcuts, setUnitShortcuts } from './lessonShortcuts'
import { lessonUnits } from './lessonUnits'
import { timecodeLock } from './timecodeLock'

vi.mock('@/components/ui/dom-tooltip', () => ({ mountDomTooltip: vi.fn(), unmountDomTooltip: vi.fn() }))

it('widget dopo il timecode o il titolo, solo per unità ammesse, senza cambiare il testo', () => {
  const doc = '## 1. Sezione\n### 1.1 Prima\n00:02\nTesto.\n### 1.2 Seconda\nSenza audio.\n### 1.3 Organizzazione\nOrari.'
  const parent = document.createElement('div')
  const view = new EditorView({ parent, state: EditorState.create({ doc, extensions: [lessonUnits, timecodeLock, lessonShortcuts] }) })
  const navigate = vi.fn()
  const options = { lessonId: 7, units: ['1.1', '1.2'], navigate }
  view.dispatch({ effects: setUnitShortcuts.of(options) })
  expect(parent.querySelectorAll('.rt-unit-shortcuts a')).toHaveLength(4)
  const timed = parent.querySelector('.rt-timecode')!
  expect(timed.parentElement!.querySelector('.rt-unit-shortcuts')).not.toBeNull()
  expect(parent.querySelector('[data-unit-id="1.2"] .rt-unit-shortcuts')).not.toBeNull()
  expect(parent.querySelector('[data-unit-id="1.3"] .rt-unit-shortcuts')).toBeNull()
  const link = parent.querySelector<HTMLAnchorElement>('a[aria-label="Studia l\'unità 1.2"]')!
  fireEvent.click(link)
  expect(navigate).toHaveBeenCalledExactlyOnceWith('/studio/lezione/7?unita=1.2')
  const modified = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true })
  // Si ferma solo il browser finto: il gestore della scorciatoia deve lasciare il clic libero.
  link.addEventListener('click', event => { expect(event.defaultPrevented).toBe(false); event.preventDefault() }, { once: true })
  link.dispatchEvent(modified)
  expect(navigate).toHaveBeenCalledTimes(1)
  view.dispatch({ effects: setUnitShortcuts.of({ ...options }) })
  expect(parent.querySelectorAll('.rt-unit-shortcuts a')).toHaveLength(4)
  const beforeTyping = parent.querySelector('.rt-unit-shortcuts')
  view.dispatch({ changes: { from: doc.indexOf('Testo.'), insert: 'Nuovo ' } })
  expect(parent.querySelector('.rt-unit-shortcuts')).toBe(beforeTyping)
  expect(parent.querySelectorAll('.rt-unit-shortcuts a')).toHaveLength(4)
  expect(view.state.doc.toString()).toBe(doc.replace('Testo.', 'Nuovo Testo.'))
  const links = Array.from(parent.querySelectorAll('a'))
  view.destroy()
  for (const node of links) expect(unmountDomTooltip).toHaveBeenCalledWith(node)
})
