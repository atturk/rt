/**
 * Converte il Markdown di un'unità per la copia negli appunti (Cmd+Alt+C):
 * - Titolo come intestazione Markdown (es. `## 4.2 Titolo`)
 * - Mantiene grassetto, corsivo, elenchi, formule $...$
 * - Rimuove righe di immagini, allegati e commenti interni di RT
 */
export function formatUnitAsMarkdown(unit: { id?: string; title: string; markdown?: string | null }): string {
  const heading = unit.id ? `## ${unit.id} ${unit.title}` : `## ${unit.title}`
  let raw = unit.markdown || ''

  // Togli commenti interni di RT (<!-- ... -->)
  raw = raw.replace(/<!--[\s\S]*?-->/g, '')

  // Dividi per righe e filtra le righe delle immagini e degli allegati
  const lines = raw.split('\n')
  const keptLines = lines.filter((line) => {
    const trimmed = line.trim()
    if (!trimmed) return true
    // Immagini markdown ![alt](url) o tag <img ...>
    if (/^!\[.*?\]\(.*?\)$/.test(trimmed) || /^<img\b[^>]*>$/.test(trimmed)) {
      return false
    }
    // Righe di allegati (es. [allegato](doc.pdf) o [nome](assets/...))
    if (/^\[.*?\]\(.*?\)$/.test(trimmed)) {
      return false
    }
    return true
  })

  // Normalizza righe vuote consecutive
  const cleaned = keptLines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
  return cleaned ? `${heading}\n\n${cleaned}` : heading
}
