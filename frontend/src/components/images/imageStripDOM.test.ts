import { describe, expect, it, vi } from 'vitest'
import { buildImageStripDOM, mountDocumentImageStrips } from './imageStripDOM'

describe('imageStripDOM', () => {
  it('costruisce solo miniature, badge e pulsanti di scorrimento', () => {
    const images = [
      { src: '/img1.png', alt: 'Doc.pdf, pagina 1', docName: 'Doc.pdf', pageNumber: 1 },
      { src: '/img2.png', alt: 'Doc.pdf, pagina 2', docName: 'Doc.pdf', pageNumber: 2 },
    ]
    const strip = buildImageStripDOM(images)
    expect(strip.classList.contains('rt-strip')).toBe(true)
    expect(strip.dataset.n).toBe('2')

    expect(strip.querySelector('.rt-strip-head')).toBeNull()

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

  it('con il pannello aperto emette rt-media-select e non apre il visualizzatore; con il pannello chiuso apre il visualizzatore', () => {
    const images = [
      { src: '/api/v1/lessons/1/assets/images/foto.png', alt: 'Doc.pdf, pagina 1', docName: 'Doc.pdf', pageNumber: 1 },
    ]
    const strip = buildImageStripDOM(images)
    const thumb = strip.querySelector('.thumb') as HTMLButtonElement

    // 1. Con il pannello aperto
    const panelDiv = document.createElement('div')
    panelDiv.setAttribute('data-testid', 'enrichment-panel')
    document.body.appendChild(panelDiv)

    const mediaSelectListener = vi.fn()
    const viewerOpenListener = vi.fn()
    window.addEventListener('rt-media-select', mediaSelectListener)
    window.addEventListener('rt-image-viewer-open', viewerOpenListener)

    thumb.click()

    expect(mediaSelectListener).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { name: 'foto.png' } }),
    )
    expect(viewerOpenListener).not.toHaveBeenCalled()

    // 2. Con il pannello chiuso
    panelDiv.remove()
    mediaSelectListener.mockClear()
    viewerOpenListener.mockClear()

    thumb.click()

    expect(mediaSelectListener).not.toHaveBeenCalled()
    expect(viewerOpenListener).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { images, index: 0 } }),
    )

    window.removeEventListener('rt-media-select', mediaSelectListener)
    window.removeEventListener('rt-image-viewer-open', viewerOpenListener)
  })

  it('monta solo le immagini della sezione, con bottone prima del timer e chiusa per default', () => {
    const container = document.createElement('div')
    container.innerHTML = `<h3 data-unit-id="1.1">Titolo<span class="rt-unit-meta"><button class="rt-timecode">00:00</button></span></h3>
      <p data-unit-timecode="1.1">00:00</p>
      <p><img src="/img1.png" alt="Doc.pdf, pagina 1" /></p>
      <p><img src="/img2.png" alt="Doc.pdf, pagina 2" /></p>
      <p>Testo</p><p><img src="/single.png" alt="Singola" /></p>`
    document.body.append(container)
    const original = container.innerHTML
    const cleanup = mountDocumentImageStrips(container, [{ unit_id: '1.1', immagini_sezione: ['img1.png', 'img2.png'] }])
    expect(container.querySelectorAll('.rt-image-strip-slot')).toHaveLength(1)
    const slot = container.querySelector<HTMLElement>('.rt-image-strip-slot')!
    expect(slot.hidden).toBe(true)
    const button = container.querySelector<HTMLButtonElement>('.rt-unit-images-button')!
    expect(button.textContent).toBe('2')
    expect(button.nextElementSibling).toHaveClass('rt-timecode')
    button.click()
    expect(slot.hidden).toBe(false)
    expect(button.getAttribute('aria-label')).toBe('Nascondi le immagini')
    expect(container.querySelectorAll('p img')).toHaveLength(1)
    button.click()
    expect(slot.hidden).toBe(true)
    cleanup()
    expect(container.innerHTML.replace(/>\s+</g, '><')).toBe(original.replace(/>\s+</g, '><'))
    container.remove()
  })
  it('non interpreta come sezione una immagine nel testo o senza metadati API', () => {
    const container = document.createElement('div')
    container.innerHTML = '<h3 data-unit-id="1.1">Titolo</h3><p><img src="/a.png#w=320"></p>'
    const cleanup = mountDocumentImageStrips(container, [{ unit_id: '1.1', immagini_sezione: ['a.png'] }])
    expect(container.querySelector('.rt-strip')).toBeNull()
    cleanup()
  })
})

it('trascinando una miniatura conserva la larghezza naturale per l’inserimento nel testo', () => {
  const strip = buildImageStripDOM([{ src: '/small.png', alt: 'Piccola', docName: 'Piccola' }], { fromUnit: '1.1' })
  const thumb = strip.querySelector<HTMLButtonElement>('.thumb')!
  Object.defineProperty(thumb.querySelector('img'), 'naturalWidth', { value: 160 })
  const setData = vi.fn()
  const event = new Event('dragstart', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: { setData } })
  thumb.dispatchEvent(event)
  expect(setData).toHaveBeenCalledWith('application/x-rt-section-image', JSON.stringify({ name: 'small.png', fromUnit: '1.1', width: 160 }))
})
