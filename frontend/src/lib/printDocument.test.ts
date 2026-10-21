import { describe, expect, it } from 'vitest'
import { extractPageCaption, transformPrintDom, waitForImagesLoaded } from './printDocument'

describe('extractPageCaption', () => {
  it('estrae pag. N solo se alt finisce con pagina N', () => {
    expect(extractPageCaption('slide 1 pagina 34')).toBe('pag. 34')
    expect(extractPageCaption('figura Pagina 7')).toBe('pag. 7')
    expect(extractPageCaption('pagina 100')).toBe('pag. 100')
    expect(extractPageCaption('diagramma senza numero')).toBeNull()
    expect(extractPageCaption('pagina 34 con altro testo')).toBeNull()
    expect(extractPageCaption('')).toBeNull()
  })
})

describe('transformPrintDom', () => {
  it('1 immagine: centrata a mezza colonna (classe pdf-grid-single)', () => {
    const root = document.createElement('div')
    root.innerHTML = '<h3>Unità</h3><p><img src="1.png" alt="figura" /></p>'
    transformPrintDom(root)

    const grid = root.querySelector('.pdf-image-grid')
    expect(grid).not.toBeNull()
    expect(grid?.classList.contains('pdf-grid-single')).toBe(true)
    const cards = grid?.querySelectorAll('.pdf-image-card')
    expect(cards).toHaveLength(1)
    expect(cards?.[0].querySelector('figcaption')).toBeNull()
  })

  it('2 immagini: una riga (classe pdf-grid-multi, 2 card)', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="slide 1 pagina 10" /></p>
      <p><img src="2.png" alt="slide 2" /></p>
    `
    transformPrintDom(root)

    const grid = root.querySelector('.pdf-image-grid')
    expect(grid).not.toBeNull()
    expect(grid?.classList.contains('pdf-grid-multi')).toBe(true)
    expect(grid?.classList.contains('pdf-grid-odd')).toBe(false)
    const cards = grid?.querySelectorAll('.pdf-image-card')
    expect(cards).toHaveLength(2)
    // Didascalia solo per la prima
    expect(cards?.[0].querySelector('figcaption')?.textContent).toBe('pag. 10')
    expect(cards?.[1].querySelector('figcaption')).toBeNull()
  })

  it('3 immagini: due righe con l\'ultima al centro (pdf-grid-odd e pdf-card-last-odd)', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="slide 1" /></p>
      <p><img src="2.png" alt="slide 2" /></p>
      <p><img src="3.png" alt="slide 3 pagina 42" /></p>
    `
    transformPrintDom(root)

    const grid = root.querySelector('.pdf-image-grid')
    expect(grid).not.toBeNull()
    expect(grid?.classList.contains('pdf-grid-multi')).toBe(true)
    expect(grid?.classList.contains('pdf-grid-odd')).toBe(true)
    const cards = grid?.querySelectorAll('.pdf-image-card')
    expect(cards).toHaveLength(3)
    expect(cards?.[2].classList.contains('pdf-card-last-odd')).toBe(true)
    expect(cards?.[2].querySelector('figcaption')?.textContent).toBe('pag. 42')
  })

  it('immagine nel testo: resta dov\'è, fuori dalla griglia', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="slide 1" /></p>
      <p>Paragrafo di testo intermedio</p>
      <p><img src="2.png" alt="slide 2" /></p>
    `
    transformPrintDom(root)

    const grids = root.querySelectorAll('.pdf-image-grid')
    expect(grids).toHaveLength(1)
    expect(grids[0].querySelector('img')?.getAttribute('src')).toBe('1.png')
    expect(root.querySelector('p:last-child img')?.getAttribute('src')).toBe('2.png')
  })

  it('larghezza scelta dall\'utente: resta fuori dalla griglia con la sua larghezza', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="slide 1" width="320" /></p>
    `
    transformPrintDom(root)

    expect(root.querySelector('.pdf-image-grid')).toBeNull()
    expect(root.querySelector('p img')?.getAttribute('width')).toBe('320')
  })
})

describe('waitForImagesLoaded', () => {
  it('data-ready scatta solo dopo il caricamento delle immagini', async () => {
    const root = document.createElement('div')
    const img = document.createElement('img')
    // Simula immagine non ancora caricata
    Object.defineProperty(img, 'complete', { value: false, writable: true })
    Object.defineProperty(img, 'naturalWidth', { value: 0, writable: true })
    root.appendChild(img)

    let loaded = false
    const promise = waitForImagesLoaded(root).then(() => {
      loaded = true
    })

    expect(loaded).toBe(false)
    // Fai scattare l'evento load
    img.dispatchEvent(new Event('load'))
    await promise
    expect(loaded).toBe(true)
  })
})

it('PDF: il timecode non interrompe la griglia e la larghezza nel testo resta intatta', () => {
  const root = document.createElement('div')
  root.innerHTML = '<h3 data-unit-id="1.1">Unità</h3><p data-unit-timecode="1.1">00:00</p><p><img src="a.png"></p><p><img src="b.png"></p><p><img src="inline.png" width="320"></p><p>Testo</p>'
  transformPrintDom(root)
  expect(root.querySelectorAll('.pdf-image-grid .pdf-image-card')).toHaveLength(2)
  expect(root.querySelector('p img[width]')).toHaveAttribute('width', '320')
})
