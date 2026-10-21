import { COPY_FORMAT_DEFAULT, selectionHtml } from './copyFormat'

function select(html: string) {
  document.body.innerHTML = `<div id="root">${html}</div>`
  const range = document.createRange()
  range.selectNodeContents(document.getElementById('root')!)
  return range
}

it('tiene grassetto, corsivo ed evidenziazioni ma non classi e colori', () => {
  const range = select('<p class="x" style="color: red">La <strong style="color: red">densità</strong> <em>di</em> <span class="rt-hl rt-hl-1">carica</span></p>')
  expect(selectionHtml(range, COPY_FORMAT_DEFAULT)).toBe('<p>La <b>densità</b> <i>di</i> <span style="background-color: #bbf7d0">carica</span></p>')
})

it('toglie gli stili esclusi nelle impostazioni', () => {
  const range = select('<p>La <strong>densità</strong> <em>di</em> <span class="rt-hl rt-hl-1">carica</span></p>')
  expect(selectionHtml(range, { bold: false, italic: false, highlights: false, color: false })).toBe('<p>La densità di carica</p>')
})

it('le formule diventano sorgente per MathJax', () => {
  const range = select('<p>vale <math class="rt-math" data-rt-source="$$\\rho_V = 1$$"><mi>ρ</mi></math></p>')
  expect(selectionHtml(range, COPY_FORMAT_DEFAULT)).toBe('<p>vale \\[\\rho_V = 1\\]</p>')
})

it('una parte di una parola in grassetto resta in grassetto', () => {
  document.body.innerHTML = '<p><strong id="b">densità</strong></p>'
  const text = document.getElementById('b')!.firstChild!
  const range = document.createRange()
  range.setStart(text, 0)
  range.setEnd(text, 4)
  expect(selectionHtml(range, COPY_FORMAT_DEFAULT)).toBe('<b>dens</b>')
})
