import { mountDomTooltip, unmountDomTooltip } from '@/components/ui/dom-tooltip'
import { isEnrichmentPanelOpen } from '@/components/shell/globalFileDropUtils'
import { parseImageAlt, type ImageItem } from './imageUtils'
import { RT_SECTION_IMAGE_DRAG_TYPE } from '@/components/lesson/imageSections'

const PAPERCLIP_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="rt-strip-clip"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`
const PREV_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>`
const NEXT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>`

export const MIN_STRIP_IMAGES = 1

export type StripOptions = {
  onImageClick?: (index: number) => void
  fromUnit?: string
}

/**
 * Costruisce l'elemento DOM di una striscia di immagini conforme ai wireframe RT 4.2.6.
 */
export function buildImageStripDOM(images: ImageItem[], options?: StripOptions): HTMLElement {
  const container = document.createElement('div')
  container.className = 'rt-strip'
  container.dataset.n = String(images.length)

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
    const name = decodeURIComponent(img.src.split('/').pop()?.split('#')[0] ?? '')
    thumb.dataset.imageName = name
    if (options?.fromUnit) {
      thumb.draggable = true
      thumb.ondragstart = event => {
        event.stopPropagation()
        thumb.closest('.cm-editor')?.classList.add('rt-dragging-images')
        event.dataTransfer?.setData(RT_SECTION_IMAGE_DRAG_TYPE, JSON.stringify({ name, fromUnit: options.fromUnit, width: thumb.querySelector('img')?.naturalWidth || 480 }))
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
      }
    }
    const pageLabel = img.pageNumber !== undefined ? `pagina ${img.pageNumber}` : `${idx + 1}`
    thumb.setAttribute('aria-label', `Apri ${pageLabel}`)

    const imageEl = document.createElement('img')
    imageEl.src = img.src
    imageEl.alt = img.alt
    imageEl.loading = 'lazy'
    imageEl.draggable = false
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
      if (isEnrichmentPanelOpen()) {
        const rawName = img.src.split('/').pop()?.split('#')[0]
        const name = rawName ? decodeURIComponent(rawName) : ''
        window.dispatchEvent(
          new CustomEvent('rt-media-select', {
            detail: { name },
          }),
        )
      } else {
        window.dispatchEvent(
          new CustomEvent('rt-image-viewer-open', {
            detail: { images, index: idx },
          }),
        )
      }
    }
    thumbs.append(thumb)
  })

  const nextBtn = document.createElement('button')
  nextBtn.type = 'button'
  nextBtn.className = 'nav next'
  nextBtn.setAttribute('aria-label', 'Scorri a destra')
  nextBtn.innerHTML = NEXT_ICON

  if (images.length > 1) {
    rail.append(prevBtn, thumbs, nextBtn)
  } else {
    rail.append(thumbs)
  }
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

  return container
}

/** Bottone condiviso da editor, lettura e Studio. */
export function buildUnitImagesButton(unitId: string, count: number, open: boolean, toggle: () => void): HTMLButtonElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'rt-unit-images-button'
  button.classList.toggle('empty', count === 0)
  button.classList.toggle('active', open)
  button.dataset.unitImages = unitId
  button.setAttribute('aria-expanded', String(open))
  const label = open ? 'Nascondi le immagini' : 'Mostra le immagini'
  button.setAttribute('aria-label', label)
  mountDomTooltip(button, label)
  button.innerHTML = PAPERCLIP_ICON
  if (count) {
    const number = document.createElement('span')
    number.textContent = String(count)
    button.append(number)
  }
  button.onclick = event => { event.preventDefault(); event.stopPropagation(); toggle() }
  return button
}

type DocumentImageSection = { unit_id: string; immagini_sezione?: string[]; start_formatted?: string | null }

/** Solo i paragrafi iniziali dichiarati dall'API appartengono alla sezione. */
export function mountDocumentImageStrips(root: HTMLElement, sections: DocumentImageSection[]): () => void {
  const cleanups: (() => void)[] = []
  for (const section of sections) {
    const names = section.immagini_sezione ?? []
    if (!names.length) continue
    const unitRoot = root.dataset.unitId === section.unit_id ? root : null
    const heading = unitRoot ? root.previousElementSibling as HTMLElement | null
      : root.querySelector<HTMLElement>(`[data-unit-id="${CSS.escape(section.unit_id)}"]`)
    if (!heading) continue
    const originals: HTMLElement[] = []
    const images: ImageItem[] = []
    let next = unitRoot ? root.firstElementChild : heading.nextElementSibling
    // Il timecode originale è nascosto dal renderer, resta nel DOM.
    if (next?.hasAttribute('data-unit-timecode')) next = next.nextElementSibling
    let index = 0
    while (next && index < names.length) {
      if (!next.matches('p, figure') || next.textContent?.trim()) break
      const imgs = Array.from(next.querySelectorAll('img'))
      if (!imgs.length || imgs.some((img, offset) => img.getAttribute('src')?.includes('#w=') ||
        decodeURIComponent(img.getAttribute('src')?.split('/').pop()?.split('#')[0] ?? '') !== names[index + offset])) break
      originals.push(next as HTMLElement)
      for (const img of imgs) {
        const alt = img.getAttribute('alt') ?? ''
        images.push({ src: img.getAttribute('src') ?? '', alt, ...parseImageAlt(alt) })
        index++
      }
      next = next.nextElementSibling
    }
    if (!images.length) continue
    let meta = heading.querySelector<HTMLElement>('.rt-unit-meta')
    const createdMeta = !meta
    if (!meta) {
      meta = document.createElement('span')
      meta.className = 'rt-unit-meta'
      if (section.start_formatted) {
        const time = document.createElement('span')
        time.className = 'rt-timecode'
        time.textContent = section.start_formatted
        meta.append(time)
      }
      heading.append(meta)
    }
    const slot = document.createElement('div')
    slot.className = 'rt-image-strip-slot rt-unit-images-section'
    slot.dataset.unitImages = section.unit_id
    slot.hidden = true
    slot.append(buildImageStripDOM(images))
    originals[0].before(slot)
    originals.forEach(element => element.remove())
    const button = buildUnitImagesButton(section.unit_id, images.length, false, () => {
      slot.hidden = !slot.hidden
      button.classList.toggle('active', !slot.hidden)
      button.setAttribute('aria-expanded', String(!slot.hidden))
      const label = slot.hidden ? 'Mostra le immagini' : 'Nascondi le immagini'
      button.setAttribute('aria-label', label)
      unmountDomTooltip(button)
      mountDomTooltip(button, label)
    })
    meta.prepend(button)
    cleanups.push(() => {
      unmountDomTooltip(button)
      button.remove()
      if (createdMeta) meta.remove()
      slot.replaceWith(...originals)
    })
  }
  return () => cleanups.forEach(cleanup => cleanup())
}
