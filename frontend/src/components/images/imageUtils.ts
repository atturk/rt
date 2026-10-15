import { readPreference } from '@/lib/preferences'

export type ImageItem = {
  src: string
  alt: string
  docName: string
  pageNumber?: number
}

/**
 * Estrae il nome del documento e il numero di pagina dal testo alternativo dell'immagine.
 * Esempi:
 * - "4. Emostasi coagulazione trombosi embolia.pdf, pagina 3" -> { docName: "4. Emostasi...", pageNumber: 3 }
 * - "Documento.pdf, p. 12" -> { docName: "Documento.pdf", pageNumber: 12 }
 * - "Documento.pdf, pag. 5" -> { docName: "Documento.pdf", pageNumber: 5 }
 * - "Schema fisiologico" -> { docName: "Schema fisiologico" }
 */
export function parseImageAlt(alt: string): { docName: string; pageNumber?: number } {
  const clean = alt.replace(/[\r\n]+/g, ' ').trim()
  const match = /^(.*?)(?:,\s*(?:pagina|pag\.|p\.)\s*(\d+))$/i.exec(clean)
  if (match && match[1].trim()) {
    return {
      docName: match[1].trim(),
      pageNumber: parseInt(match[2], 10),
    }
  }
  return { docName: clean || 'Documento' }
}

/**
 * Crea le etichette per l'intestazione della striscia:
 * - countPill: "N pagine" (o "1 pagina")
 * - docLabel: "Documento.pdf, p. 3–6" o elenco dei documenti
 */
export function formatStripLabel(images: ImageItem[]): { countPill: string; docLabel: string } {
  const n = images.length
  const countPill = n === 1 ? '1 pagina' : `${n} pagine`

  if (n === 0) return { countPill, docLabel: '' }

  const firstDoc = images[0].docName
  const sameDoc = images.every((img) => img.docName === firstDoc)

  if (sameDoc) {
    const pages = images.map((img) => img.pageNumber).filter((p): p is number => p !== undefined)
    if (pages.length === images.length && pages.length > 0) {
      const min = Math.min(...pages)
      const max = Math.max(...pages)
      const isConsecutive = pages.every((p, i) => i === 0 || p === pages[i - 1] + 1)
      const pageStr = isConsecutive && min !== max ? `p. ${min}–${max}` : pages.length === 1 ? `p. ${pages[0]}` : `p. ${pages.join(', ')}`
      return {
        countPill,
        docLabel: `${firstDoc}, ${pageStr}`,
      }
    }
    return { countPill, docLabel: firstDoc }
  }

  // Documenti diversi: mostra i nomi unici
  const uniqueDocs = Array.from(new Set(images.map((img) => img.docName).filter(Boolean)))
  return {
    countPill,
    docLabel: uniqueDocs.join(', '),
  }
}

const STRIP_CLOSED_KEY = 'strip_closed'
const PREF_PREFIX = 'rt-pref:'

export function getStripClosedPreference(): boolean {
  return readPreference<boolean>(STRIP_CLOSED_KEY, false)
}

export function setStripClosedPreference(closed: boolean) {
  try {
    localStorage.setItem(PREF_PREFIX + STRIP_CLOSED_KEY, JSON.stringify(closed))
  } catch {
    // localstorage facoltativo
  }
  window.dispatchEvent(new CustomEvent('rt-strip-toggle', { detail: { closed } }))
}
