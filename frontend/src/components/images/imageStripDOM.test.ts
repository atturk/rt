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

  it('mountDocumentImageStrips raggruppa paragrafi di immagini consecutive in una striscia', () => {
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

    // Le due immagini consecutive sono state trasformate in uno slot con striscia
    const slots = container.querySelectorAll('.rt-image-strip-slot')
    expect(slots).toHaveLength(1)

    const strip = slots[0].querySelector('.rt-strip')
    expect(strip).not.toBeNull()
    expect((strip as HTMLElement)?.dataset.n).toBe('2')

    // L'immagine singola resta un normale paragrafo img
    const remainingPs = container.querySelectorAll('p')
    const hasSingleImg = Array.from(remainingPs).some((p) => p.querySelector('img[src="/single.png"]'))
    expect(hasSingleImg).toBe(true)

    cleanup()
    container.remove()
  })
})
