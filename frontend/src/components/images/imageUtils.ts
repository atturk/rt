export type ImageItem = {
  src: string
  alt: string
  caption?: string
  docName: string
  pageNumber?: number
  from?: number
  interactiveUrl?: string
}

/**
 * Estrae didascalia opzionale, nome del documento e numero di pagina dal testo alternativo.
 * Separatore tra titolo e riferimento: " — " (spazio, trattino lungo, spazio); divide sull'ULTIMO.
 * Esempi:
 * - "Cascata — 4. Emostasi.pdf, pagina 3" -> { caption: "Cascata", docName: "4. Emostasi.pdf", pageNumber: 3 }
 * - "4. Emostasi coagulazione trombosi embolia.pdf, pagina 3" -> { docName: "4. Emostasi...", pageNumber: 3 }
 * - "Schema — foto.jpg" -> { caption: "Schema", docName: "foto.jpg" }
 * - "Schema fisiologico" -> { docName: "Schema fisiologico" }
 */
export function parseImageAlt(alt: string): { caption?: string; docName: string; pageNumber?: number } {
  const clean = alt.replace(/[\r\n]+/g, ' ').trim()
  const sepIndex = clean.lastIndexOf(' — ')
  let caption: string | undefined
  let rest = clean
  if (sepIndex > 0) {
    const candidate = clean.slice(0, sepIndex).trim()
    const after = clean.slice(sepIndex + 3).trim()
    if (candidate && after) {
      caption = candidate
      rest = after
    }
  }
  const match = /^(.*?)(?:,\s*(?:pagina|pag\.|p\.)\s*(\d+))$/i.exec(rest)
  if (match && match[1].trim()) {
    return {
      ...(caption ? { caption } : {}),
      docName: match[1].trim(),
      pageNumber: parseInt(match[2], 10),
    }
  }
  return {
    ...(caption ? { caption } : {}),
    docName: rest || 'Documento',
  }
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
