import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buildImageStripDOM, mountDocumentImageStrips } from './imageStripDOM'
import { setStripClosedPreference } from './imageUtils'

describe('imageStripDOM', () => {
  beforeEach(() => {
    setStripClosedPreference(false)
  })

  it('costruisce la striscia con intestazione, miniature e pulsanti', () => {
    const images = [
      { src: '/img1.png', alt: 'Doc.pdf, pagina 1', docName: 'Doc.pdf', pageNumber: 1 },
      { src: '/img2.png', alt: 'Doc.pdf, pagina 2', docName: 'Doc.pdf', pageNumber: 2 },
    ]
    const strip = buildImageStripDOM(images)
    expect(strip.classList.contains('rt-strip')).toBe(true)
    expect(strip.dataset.n).toBe('2')

    const name = strip.querySelector('.name')
    expect(name?.textContent).toContain('2 pagine')
    expect(name?.textContent).toContain('Doc.pdf, p. 1–2')

    const thumbs = strip.querySelectorAll('.thumb')
    expect(thumbs).toHaveLength(2)

    const firstThumb = thumbs[0] as HTMLButtonElement
    expect(firstThumb.getAttribute('aria-label')).toBe('Apri pagina 1')
    expect(firstThumb.querySelector('.pg')?.textContent).toBe('p. 1')
  })

  it('invia l’evento di apertura del visore al clic su una miniatura', () => {
    const images = [
      { src: '/img1.png', alt: 'Doc.pdf, pagina 1', docName: 'Doc.pdf', pageNumber: 1 },
      { src: '/img2.png', alt: 'Doc.pdf, pagina 2', docName: 'Doc.pdf', pageNumber: 2 },
    ]
    const onImageClick = vi.fn()
    const strip = buildImageStripDOM(images, { onImageClick })

    let eventDetail: unknown = null
    const listener = (e: Event) => {
      eventDetail = (e as CustomEvent).detail
    }
    window.addEventListener('rt-image-viewer-open', listener)

    const secondThumb = strip.querySelectorAll('.thumb')[1] as HTMLButtonElement
    secondThumb.click()

    expect(onImageClick).toHaveBeenCalledWith(1)
    expect(eventDetail).toEqual({ images, index: 1 })

    window.removeEventListener('rt-image-viewer-open', listener)
  })

  it('mountDocumentImageStrips trasforma sia immagini consecutive che immagini singole in strisce', () => {
    const container = document.createElement('div')
    container.innerHTML = `
      <p>Primo testo</p>
      <p><img src="/img1.png" alt="Doc.pdf, pagina 1" /></p>
      <p><img src="/img2.png" alt="Doc.pdf, pagina 2" /></p>
      <p>Secondo testo</p>
      <p><img src="/single.png" alt="Singola" /></p>
      <p>Terzo testo</p>
    `
    document.body.append(container)

    const cleanup = mountDocumentImageStrips(container)

    // Ci sono 2 slot: uno per la serie di 2 immagini e uno per l'immagine singola
    const slots = container.querySelectorAll('.rt-image-strip-slot')
    expect(slots).toHaveLength(2)

    const strip1 = slots[0].querySelector('.rt-strip')
    expect(strip1).not.toBeNull()
    expect((strip1 as HTMLElement)?.dataset.n).toBe('2')

    const strip2 = slots[1].querySelector('.rt-strip')
    expect(strip2).not.toBeNull()
    expect((strip2 as HTMLElement)?.dataset.n).toBe('1')

    // Nessun paragrafo di immagine rimasto
    const remainingImgs = container.querySelectorAll('p img')
    expect(remainingImgs).toHaveLength(0)

    // Lo smontaggio rimette i paragrafi originali
    cleanup()
    const restoredImgs = container.querySelectorAll('p img')
    expect(restoredImgs).toHaveLength(3)

    container.remove()
  })
})
