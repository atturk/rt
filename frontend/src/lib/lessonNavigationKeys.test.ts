import { afterEach, expect, it } from 'vitest'
import { lessonArrowAllowed } from './lessonNavigationKeys'
afterEach(() => { document.body.replaceChildren(); window.getSelection()?.removeAllRanges() })
function arrow(target: Element, options: KeyboardEventInit = {}) {
  let allowed = false
  target.addEventListener('keydown', event => { allowed = lessonArrowAllowed(event as KeyboardEvent) }, { once: true })
  target.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true, ...options }))
  return allowed
}
it.each(['input', 'textarea', 'select', '[contenteditable]', '.cm-editor', '[role=slider]', '[role=menu]', '[role=listbox]', '[role=dialog]', '[data-testid=audio-player]'])('esclude %s e i suoi figli', selector => {
  const container = document.createElement(selector.startsWith('[') || selector.startsWith('.') ? 'div' : selector)
  if (selector === '[contenteditable]') container.setAttribute('contenteditable', 'true')
  if (selector.startsWith('[role')) container.setAttribute('role', selector.slice(6, -1))
  if (selector === '[data-testid=audio-player]') container.dataset.testid = 'audio-player'
  if (selector === '.cm-editor') container.className = 'cm-editor'
  const child = document.createElement('span'); container.append(child); document.body.append(container)
  expect(arrow(child)).toBe(false)
})
it('ammette le frecce fuori dai controlli, esclude modificatori, selezione e dialoghi', () => {
  const title = document.createElement('h1'); title.textContent = 'Lezione'; document.body.append(title)
  expect(arrow(title)).toBe(true)
  for (const modifier of ['metaKey', 'ctrlKey', 'altKey', 'shiftKey']) expect(arrow(title, { [modifier]: true })).toBe(false)
  const range = document.createRange(); range.selectNodeContents(title); window.getSelection()?.addRange(range)
  expect(arrow(title)).toBe(false)
  window.getSelection()?.removeAllRanges()
  const dialog = document.createElement('dialog'); dialog.setAttribute('open', ''); document.body.append(dialog)
  expect(arrow(title)).toBe(false)
  dialog.remove()
  title.addEventListener('keydown', event => event.preventDefault(), { once: true })
  expect(arrow(title)).toBe(false)
})
