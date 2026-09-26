/**
 * L'HTML del documento richiama le immagini con percorsi relativi alla lezione
 * (assets/images/<nome>): li porta all'endpoint dell'API che le serve.
 */
export function withImageUrls(html: string, id: number): string {
  return html.replace(/(<img\b[^>]*\bsrc=")(?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)"/g, (_m, head: string, name: string) => {
    return `${head}/api/v1/lessons/${id}/assets/images/${encodeURIComponent(name)}"`
  })
}
