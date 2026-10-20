/**
 * L'HTML del documento richiama le immagini con percorsi relativi alla lezione
 * (assets/images/<nome>): li porta all'endpoint dell'API che le serve.
 * Riconosce l'eventuale larghezza personalizzata (#w=320), la imposta come attributo
 * width e la toglie dall'URL.
 */
export function withImageUrls(html: string, id: number): string {
  return html.replace(
    /(<img\b[^>]*?\bsrc=")(?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#w=(\d+))?(")([^>]*>)/g,
    (_m, head: string, name: string, width?: string, quote?: string, tail?: string) => {
      const src = `${head}/api/v1/lessons/${id}/assets/images/${encodeURIComponent(name)}${quote}`
      if (width) {
        return `${src} width="${width}" style="max-width: 100%;"${tail}`
      }
      return `${src}${tail}`
    },
  )
}
