import { renderDelimitedMath } from './math'
import { sourceOffsets, sourceRange, sourceTextOf } from './sourceText'

const source = String.raw`Il dominio $D$ contiene $(x, y, z)$ e $$\underline{R}_{12} = R_{12}\,\underline{i}_{r12}$$, con grassetto.`

async function documentWithMath() {
  const root = document.createElement('article')
  root.innerHTML = `<p>${source.replace('grassetto', '<strong>grassetto</strong>')}</p>`
  await renderDelimitedMath(root)
  return root
}

it('conta una sola volta il sorgente con delimitatori, anche attraverso il grassetto', async () => {
  const root = await documentWithMath()
  const math = root.querySelector('math')!
  const raw = document.createElement('span')
  raw.className = 'rt-math-src'; raw.textContent = '$D$'; math.after(raw)
  const images = document.createElement('div')
  images.className = 'rt-image-strip-slot'; images.textContent = 'Immagini, avanti'; root.append(images)
  expect(sourceTextOf(root)).toBe(source)
  const range = document.createRange(); range.selectNodeContents(root)
  expect(sourceOffsets(root, range)).toEqual({ text: source, start: 0, end: source.length })
})

it('una parte di formula include tutto il token e non le annotazioni', async () => {
  const root = await documentWithMath()
  const token = root.querySelectorAll('math')[1].querySelector('mi')!.firstChild!
  const range = document.createRange(); range.setStart(token, 0); range.setEnd(token, 1)
  const result = sourceOffsets(root, range)
  expect(result.text.slice(result.start, result.end)).toBe('$(x, y, z)$')
  expect(sourceTextOf(sourceRange(root, result.start, result.end)!.cloneContents())).toBe('$(x, y, z)$')
})

it('rispetta i confini su elementi e non include la formula appena fuori dalla selezione', async () => {
  const root = await documentWithMath(), math = root.querySelector('math')!
  const range = document.createRange(); range.setStart(root, 0); range.setEndBefore(math)
  const { text, start, end } = sourceOffsets(root, range)
  expect(text.slice(start, end)).toBe('Il dominio ')
})
