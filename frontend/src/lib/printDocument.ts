/**
 * Impaginazione e trasformazioni per la pagina di stampa PDF della lezione.
 */

/**
 * Estrae la didascalia della pagina se l'alt termina con "pagina N".
 * Es: "slide 1 pagina 34" -> "pag. 34"
 */
export function extractPageCaption(alt: string): string | null {
  const match = alt.trim().match(/(?:^|\s)pagina\s+(\d+)$/i)
  return match ? `pag. ${match[1]}` : null
}

/**
 * Raggruppa immagini consecutive (in paragrafi dedicati) in una griglia a 2 colonne:
 * - 1 immagine: centrata, larga mezza colonna (~85mm);
 * - 2 immagini: una riga a 2 colonne;
 * - 3 o dispari > 1: righe a 2 colonne con l'ultima centrata a mezza colonna;
 * - testo tra immagini: due griglie separate.
 */
export function transformPrintDom(root: HTMLElement) {
  const children = Array.from(root.children)
  let currentGroup: HTMLElement[] = []

  const isImageContainer = (el: Element): boolean => {
    if (el.tagName === 'IMG') return true
    if (el.tagName === 'P') {
      const imgs = el.querySelectorAll('img')
      if (imgs.length > 0 && el.textContent?.trim() === '') {
        return true
      }
    }
    return false
  }

  const flushGroup = () => {
    if (currentGroup.length === 0) return
    const imgs: HTMLImageElement[] = []
    for (const container of currentGroup) {
      if (container.tagName === 'IMG') {
        imgs.push(container as HTMLImageElement)
      } else {
        container.querySelectorAll<HTMLImageElement>('img').forEach((img) => imgs.push(img))
      }
    }
    if (imgs.length === 0) {
      currentGroup = []
      return
    }

    const grid = document.createElement('div')
    grid.className = 'pdf-image-grid'
    grid.dataset.count = String(imgs.length)

    if (imgs.length === 1) {
      grid.classList.add('pdf-grid-single')
    } else {
      grid.classList.add('pdf-grid-multi')
      if (imgs.length % 2 === 1) {
        grid.classList.add('pdf-grid-odd')
      }
    }

    for (let i = 0; i < imgs.length; i++) {
      const img = imgs[i]
      const card = document.createElement('figure')
      card.className = 'pdf-image-card'
      if (imgs.length % 2 === 1 && i === imgs.length - 1 && imgs.length > 1) {
        card.classList.add('pdf-card-last-odd')
      }

      const imgClone = img.cloneNode(true) as HTMLImageElement
      imgClone.className = 'pdf-img'
      card.appendChild(imgClone)

      const captionText = extractPageCaption(img.alt || '')
      if (captionText) {
        const figcap = document.createElement('figcaption')
        figcap.className = 'pdf-image-caption'
        figcap.textContent = captionText
        card.appendChild(figcap)
      }

      grid.appendChild(card)
    }

    const first = currentGroup[0]
    first.replaceWith(grid)
    for (let i = 1; i < currentGroup.length; i++) {
      currentGroup[i].remove()
    }
    currentGroup = []
  }

  for (const child of children) {
    if (isImageContainer(child)) {
      currentGroup.push(child as HTMLElement)
    } else {
      flushGroup()
    }
  }
  flushGroup()
}

/**
 * Attende che tutte le immagini dentro root siano caricate.
 */
export function waitForImagesLoaded(root: HTMLElement): Promise<void> {
  const imgs = Array.from(root.querySelectorAll('img'))
  if (imgs.length === 0) return Promise.resolve()

  return new Promise((resolve) => {
    let remaining = imgs.length
    const checkOne = () => {
      remaining--
      if (remaining <= 0) resolve()
    }

    for (const img of imgs) {
      if (img.complete && img.naturalWidth !== 0) {
        checkOne()
      } else {
        img.addEventListener('load', () => checkOne(), { once: true })
        img.addEventListener('error', () => checkOne(), { once: true })
      }
    }
  })
}
