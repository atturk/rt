/**
 * Impaginazione e trasformazioni per la pagina di stampa PDF della lezione.
 */
import { parseImageAlt } from '@/components/images/imageUtils'

/**
 * Riduce il nome del documento per il riferimento discreto sotto le immagini:
 * senza estensione, '_' e '-' diventano spazi, spazi compattati, max 40 caratteri con '…'.
 */
export function shortDocName(docName: string): string {
  const withoutExt = docName.trim().replace(/\.[^.\s]+$/, '')
  const normalized = withoutExt.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim() || docName.trim()
  if (normalized.length > 40) {
    return `${normalized.slice(0, 39).trimEnd()}…`
  }
  return normalized
}

/**
 * Calcola le due righe della didascalia di stampa per una figura:
 * - riga 1 (title): titolo della slide oppure "Figura N" se manca il titolo;
 * - riga 2 (ref): "p. N" se presente, preceduto dal nome breve se la griglia mescola documenti diversi.
 */
export function buildPrintCaption(
  alt: string,
  nextFigureNumber: number,
  showDocName: boolean,
): { title: string; ref: string | null; usedUntitled: boolean } {
  const parsed = parseImageAlt(alt)
  const usedUntitled = !parsed.caption
  const title = parsed.caption || `Figura ${nextFigureNumber}`
  const parts: string[] = []
  if (showDocName && parsed.docName && parsed.pageNumber !== undefined) {
    parts.push(shortDocName(parsed.docName))
  }
  if (parsed.pageNumber !== undefined) {
    parts.push(`p. ${parsed.pageNumber}`)
  }
  return {
    title,
    ref: parts.length > 0 ? parts.join(' · ') : null,
    usedUntitled,
  }
}

/**
 * Raggruppa le immagini sotto il titolo di un'unità (paragrafi dedicati subito dopo
 * h2/h3) in una griglia a 2 colonne:
 * - 1 immagine: centrata, larga mezza colonna (~85mm);
 * - 2 immagini: una riga a 2 colonne;
 * - 3 o dispari > 1: righe a 2 colonne con l'ultima centrata a mezza colonna.
 * Le immagini nel testo, o con una larghezza scelta dall'utente (#w=), restano dove
 * sono e con la loro larghezza.
 */
export function transformPrintDom(root: HTMLElement) {
  const children = Array.from(root.children)
  let currentGroup: HTMLElement[] = []
  let afterHeading = false
  let untitledCount = 0

  const isImageContainer = (el: Element): boolean => {
    if (el.tagName === 'IMG') return !el.hasAttribute('width')
    if (el.tagName === 'P') {
      const imgs = el.querySelectorAll('img')
      if (imgs.length > 0 && el.textContent?.trim() === '' && !el.querySelector('img[width]')) {
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

    // Solo le pagine di documenti contano: le foto singole non mostrano mai il nome del file.
    const docNames = new Set(
      imgs.map((img) => parseImageAlt(img.alt || '')).filter((p) => p.pageNumber !== undefined).map((p) => p.docName),
    )
    const showDocName = docNames.size > 1

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

      const { title, ref, usedUntitled } = buildPrintCaption(img.alt || '', untitledCount + 1, showDocName)
      if (usedUntitled) untitledCount += 1

      const figcap = document.createElement('figcaption')
      figcap.className = 'pdf-image-caption'
      const titleEl = document.createElement('span')
      titleEl.className = 'pdf-image-title'
      titleEl.textContent = title
      figcap.appendChild(titleEl)
      if (ref) {
        const refEl = document.createElement('span')
        refEl.className = 'pdf-image-ref'
        refEl.textContent = ref
        figcap.appendChild(refEl)
      }
      card.appendChild(figcap)

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
    // Il timecode è già accanto al titolo; il paragrafo nascosto non interrompe la sezione.
    if (afterHeading && child.hasAttribute('data-unit-timecode')) continue
    if (afterHeading && isImageContainer(child)) {
      currentGroup.push(child as HTMLElement)
    } else {
      flushGroup()
      afterHeading = child.tagName === 'H2' || child.tagName === 'H3'
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
