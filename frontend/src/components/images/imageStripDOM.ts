import { mountDomTooltip } from '@/components/ui/dom-tooltip'
import {
  formatStripLabel,
  getStripClosedPreference,
  parseImageAlt,
  setStripClosedPreference,
  type ImageItem,
} from './imageUtils'

const PAPERCLIP_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="rt-strip-clip"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`
const CHEV_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="chev"><path d="m6 9 6 6 6-6"/></svg>`
const PREV_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>`
const NEXT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>`

export type StripOptions = {
  onImageClick?: (index: number) => void
}

/**
 * Costruisce l'elemento DOM di una striscia di immagini conforme ai wireframe RT 4.2.6.
 */
export function buildImageStripDOM(images: ImageItem[], options?: StripOptions): HTMLElement {
  const container = document.createElement('div')
  container.className = 'rt-strip'
  container.dataset.n = String(images.length)

  const { countPill, docLabel } = formatStripLabel(images)

  let closed = getStripClosedPreference()
  if (closed) container.classList.add('closed')

  const head = document.createElement('div')
  head.className = 'rt-strip-head'

  const toggleBtn = document.createElement('button')
  toggleBtn.type = 'button'
  toggleBtn.className = 'ib tg'
  toggleBtn.setAttribute('aria-expanded', String(!closed))
  toggleBtn.setAttribute('aria-label', closed ? 'Mostra le immagini' : 'Chiudi le immagini')
  toggleBtn.innerHTML = CHEV_ICON

  let cleanupTooltip: (() => void) | undefined
  const updateTooltip = () => {
    cleanupTooltip?.()
    cleanupTooltip = mountDomTooltip(toggleBtn, closed ? 'Mostra le immagini' : 'Chiudi le immagini')
  }
  updateTooltip()

  const nameSpan = document.createElement('span')
  nameSpan.className = 'name'
  nameSpan.innerHTML = `<span class="count-pill">${countPill}</span> · ${docLabel}`

  head.innerHTML = ''
  head.append(toggleBtn)
  const clipWrapper = document.createElement('span')
  clipWrapper.className = 'rt-strip-icon'
  clipWrapper.innerHTML = PAPERCLIP_ICON
  head.append(clipWrapper)
  head.append(nameSpan)
  container.append(head)

  const rail = document.createElement('div')
  rail.className = 'rail'

  const prevBtn = document.createElement('button')
  prevBtn.type = 'button'
  prevBtn.className = 'nav prev'
  prevBtn.setAttribute('aria-label', 'Scorri a sinistra')
  prevBtn.innerHTML = PREV_ICON

  const thumbs = document.createElement('div')
  thumbs.className = 'thumbs'

  images.forEach((img, idx) => {
    const thumb = document.createElement('button')
    thumb.type = 'button'
    thumb.className = 'thumb'
    const pageLabel = img.pageNumber !== undefined ? `pagina ${img.pageNumber}` : `${idx + 1}`
    thumb.setAttribute('aria-label', `Apri ${pageLabel}`)

    const imageEl = document.createElement('img')
    imageEl.src = img.src
    imageEl.alt = img.alt
    imageEl.loading = 'lazy'
    thumb.append(imageEl)

    if (img.pageNumber !== undefined) {
      const pg = document.createElement('span')
      pg.className = 'pg'
      pg.textContent = `p. ${img.pageNumber}`
      thumb.append(pg)
    }

    thumb.onclick = (e) => {
      e.preventDefault()
      e.stopPropagation()
      options?.onImageClick?.(idx)
      window.dispatchEvent(
        new CustomEvent('rt-image-viewer-open', {
          detail: { images, index: idx },
        })
      )
    }
    thumbs.append(thumb)
  })

  const nextBtn = document.createElement('button')
  nextBtn.type = 'button'
  nextBtn.className = 'nav next'
  nextBtn.setAttribute('aria-label', 'Scorri a destra')
  nextBtn.innerHTML = NEXT_ICON

  rail.append(prevBtn, thumbs, nextBtn)
  container.append(rail)

  const checkEdges = () => {
    const l = thumbs.scrollLeft > 2
    const r = thumbs.scrollLeft + thumbs.clientWidth < thumbs.scrollWidth - 2
    rail.classList.toggle('l', l)
    rail.classList.toggle('r', r)
    prevBtn.classList.toggle('show', l)
    nextBtn.classList.toggle('show', r)
  }

  thumbs.addEventListener('scroll', checkEdges, { passive: true })
  // Verifica i bordi dopo il rendering
  setTimeout(checkEdges, 50)
  setTimeout(checkEdges, 250)

  prevBtn.onclick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    thumbs.scrollBy({ left: -thumbs.clientWidth * 0.8, behavior: 'smooth' })
  }
  nextBtn.onclick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    thumbs.scrollBy({ left: thumbs.clientWidth * 0.8, behavior: 'smooth' })
  }

  const applyClosedState = (isClosed: boolean) => {
    closed = isClosed
    container.classList.toggle('closed', closed)
    toggleBtn.setAttribute('aria-expanded', String(!closed))
    toggleBtn.setAttribute('aria-label', closed ? 'Mostra le immagini' : 'Chiudi le immagini')
    updateTooltip()
    if (!closed) setTimeout(checkEdges, 50)
  }

  toggleBtn.onclick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const nextState = !closed
    setStripClosedPreference(nextState)
  }

  const onToggleEvent = (e: Event) => {
    const custom = e as CustomEvent<{ closed: boolean }>
    if (custom.detail && typeof custom.detail.closed === 'boolean') {
      applyClosedState(custom.detail.closed)
    }
  }

  window.addEventListener('rt-strip-toggle', onToggleEvent)

  // Pulizia quando il nodo viene rimosso dal DOM
  const observer = new MutationObserver(() => {
    if (!container.isConnected) {
      window.removeEventListener('rt-strip-toggle', onToggleEvent)
      thumbs.removeEventListener('scroll', checkEdges)
      cleanupTooltip?.()
      observer.disconnect()
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })

  return container
}

/**
 * Trasforma gruppi di 2 o più immagini consecutive nel DOM reso (DocumentView o Study) in una striscia.
 * Le immagini singole rimangono invariate.
 */
export function mountDocumentImageStrips(root: HTMLElement, options?: StripOptions): () => void {
  // Trova tutti i paragrafi che contengono solo immagini
  const paragraphs = Array.from(root.querySelectorAll<HTMLElement>('p, figure'))

  type ImageGroup = {
    elements: HTMLElement[]
    images: ImageItem[]
  }

  const groups: ImageGroup[] = []
  let currentElements: HTMLElement[] = []
  let currentImages: ImageItem[] = []

  const flushGroup = () => {
    if (currentImages.length >= 2) {
      groups.push({
        elements: [...currentElements],
        images: [...currentImages],
      })
    }
    currentElements = []
    currentImages = []
  }

  for (const p of paragraphs) {
    // Non toccare elementi dentro una striscia già montata
    if (p.closest('.rt-strip') || p.closest('.rt-image-strip-slot')) continue

    // Verifica se p contiene solo immagini (e testo vuoto)
    const imgs = Array.from(p.querySelectorAll('img'))
    if (imgs.length === 0) {
      flushGroup()
      continue
    }

    const textContent = p.textContent?.trim() ?? ''
    // Se c'è testo didascalico significativo oltre alle immagini, non è un paragrafo di sole immagini
    if (textContent.length > 0 && imgs.every((img) => !img.alt || !textContent.includes(img.alt.trim()))) {
      flushGroup()
      continue
    }

    // Controlla se p è adiacente all'elemento precedente del gruppo
    if (currentElements.length > 0) {
      const prev = currentElements[currentElements.length - 1]
      // Sono fratelli consecutivi? (ignorando nodi di testo vuoti)
      let sib = prev.nextSibling
      while (sib && sib.nodeType === Node.TEXT_NODE && !sib.textContent?.trim()) {
        sib = sib.nextSibling
      }
      if (sib !== p) {
        flushGroup()
      }
    }

    currentElements.push(p)
    for (const img of imgs) {
      const src = img.getAttribute('src') || ''
      const alt = img.getAttribute('alt') || ''
      const { docName, pageNumber } = parseImageAlt(alt)
      currentImages.push({ src, alt, docName, pageNumber })
    }
  }
  flushGroup()

  const mountedSlots: HTMLElement[] = []

  for (const group of groups) {
    const slot = document.createElement('div')
    slot.className = 'rt-image-strip-slot'
    const stripEl = buildImageStripDOM(group.images, options)
    slot.append(stripEl)

    const first = group.elements[0]
    first.before(slot)
    group.elements.forEach((el) => {
      el.remove()
    })
    mountedSlots.push(slot)
  }

  return () => {
    mountedSlots.forEach((slot) => slot.remove())
  }
}
