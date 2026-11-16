import { describe, expect, it } from 'vitest'
import { buildPrintCaption, shortDocName, transformPrintDom, waitForImagesLoaded } from './printDocument'

describe('shortDocName', () => {
  it('toglie estensione, sostituisce _ e - con spazio, compatta e taglia a 40 caratteri', () => {
    expect(shortDocName('Lez2parte1-segnale_e_informazione.pdf')).toBe('Lez2parte1 segnale e informazione')
    expect(shortDocName('4. Emostasi coagulazione trombosi embolia.pdf')).toBe('4. Emostasi coagulazione trombosi embol…')
    expect(shortDocName('4. Emostasi coagulazione trombosi embolia.pdf').length).toBe(40)
  })
})

describe('buildPrintCaption', () => {
  it('mostra titolo e p. N senza nome documento nella griglia omogenea', () => {
    expect(buildPrintCaption('Cascata coagulativa — Emostasi.pdf, pagina 34', 1, false)).toEqual({
      title: 'Cascata coagulativa',
      ref: 'p. 34',
      usedUntitled: false,
    })
  })

  it('usa Figura N per immagini senza titolo e solo il titolo per foto singole', () => {
    expect(buildPrintCaption('Emostasi.pdf, pagina 7', 2, false)).toEqual({
      title: 'Figura 2',
      ref: 'p. 7',
      usedUntitled: true,
    })
    expect(buildPrintCaption('Schema sinapsi — foto.jpg', 3, false)).toEqual({
      title: 'Schema sinapsi',
      ref: null,
      usedUntitled: false,
    })
  })
})

describe('transformPrintDom', () => {
  it('1 immagine: centrata a mezza colonna (classe pdf-grid-single) con Figura 1 se senza titolo', () => {
    const root = document.createElement('div')
    root.innerHTML = '<h3>Unità</h3><p><img src="1.png" alt="figura" /></p>'
    transformPrintDom(root)

    const grid = root.querySelector('.pdf-image-grid')
    expect(grid).not.toBeNull()
    expect(grid?.classList.contains('pdf-grid-single')).toBe(true)
    const cards = grid?.querySelectorAll('.pdf-image-card')
    expect(cards).toHaveLength(1)
    expect(cards?.[0].querySelector('.pdf-image-title')?.textContent).toBe('Figura 1')
    expect(cards?.[0].querySelector('.pdf-image-ref')).toBeNull()
  })

  it('2 immagini: stessa fonte mostra solo p. N; contatore Figura N solo per immagini senza titolo', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="Potenziale d'azione — Slide.pdf, pagina 10" /></p>
      <p><img src="2.png" alt="Slide.pdf, pagina 11" /></p>
      <p>Testo intermedio</p>
      <h3>Altra unità</h3>
      <p><img src="3.png" alt="Schema neurone — foto.jpg" /></p>
      <p><img src="4.png" alt="Slide.pdf, pagina 12" /></p>
    `
    transformPrintDom(root)

    const grids = root.querySelectorAll('.pdf-image-grid')
    expect(grids).toHaveLength(2)
    const firstCards = grids[0].querySelectorAll('.pdf-image-card')
    expect(firstCards[0].querySelector('.pdf-image-title')?.textContent).toBe("Potenziale d'azione")
    expect(firstCards[0].querySelector('.pdf-image-ref')?.textContent).toBe('p. 10')
    expect(firstCards[1].querySelector('.pdf-image-title')?.textContent).toBe('Figura 1')
    expect(firstCards[1].querySelector('.pdf-image-ref')?.textContent).toBe('p. 11')

    const secondCards = grids[1].querySelectorAll('.pdf-image-card')
    expect(secondCards[0].querySelector('.pdf-image-title')?.textContent).toBe('Schema neurone')
    expect(secondCards[0].querySelector('.pdf-image-ref')?.textContent).toBe('foto')
    expect(secondCards[1].querySelector('.pdf-image-title')?.textContent).toBe('Figura 2')
    expect(secondCards[1].querySelector('.pdf-image-ref')?.textContent).toBe('Slide · p. 12')
  })

  it('3 immagini: due documenti diversi mostrano nome breve + p. N e foto singola mostra solo il titolo', () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <h3>Unità</h3>
      <p><img src="1.png" alt="Ipossia, ischemia — Lez_1-patologia.pdf, pagina 4" /></p>
      <p><img src="2.png" alt="Necrosi — Lez_2-danno.pdf, pagina 8" /></p>
      <p><img src="3.png" alt="Apoptosi — Lez_2-danno.pdf, pagina 9" /></p>
      <h3>Foto</h3>
      <p><img src="4.png" alt="Schema sinapsi — PHOTO-2026-11-16.jpg" /></p>
    `
    transformPrintDom(root)

    const grids = root.querySelectorAll('.pdf-image-grid')
    expect(grids[0].classList.contains('pdf-grid-multi')).toBe(true)
    expect(grids[0].classList.contains('pdf-grid-odd')).toBe(true)
    const cards = grids[0].querySelectorAll('.pdf-image-card')
    expect(cards).toHaveLength(3)
    expect(cards[2].classList.contains('pdf-card-last-odd')).toBe(true)
    expect(cards[0].querySelector('.pdf-image-title')?.textContent).toBe('Ipossia, ischemia')
    expect(cards[0].querySelector('.pdf-image-ref')?.textContent).toBe('Lez 1 patologia · p. 4')
    expect(cards[2].querySelector('.pdf-image-title')?.textContent).toBe('Apoptosi')
    expect(cards[2].querySelector('.pdf-image-ref')?.textContent).toBe('Lez 2 danno · p. 9')

    const photoCard = grids[1].querySelector('.pdf-image-card')!
    expect(photoCard.querySelector('.pdf-image-title')?.textContent).toBe('Schema sinapsi')
    expect(photoCard.querySelector('.pdf-image-ref')).toBeNull()
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
