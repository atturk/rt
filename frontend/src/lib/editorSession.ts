/**
 * L'editor della lezione tiene un lease che blocca i job della lezione. Le azioni che avviano
 * un job dalla stessa scheda (Arricchimento: carica PDF/foto, descrivi, analizza, genera)
 * prima salvano la bozza e lasciano il lease, come fa la Verifica: altrimenti il server le
 * rifiuta con «Il documento è in modifica in un'altra scheda».
 */
const flushers = new Map<number, () => Promise<void>>()

export function registerEditorFlush(lessonId: number, flush: () => Promise<void>): () => void {
  flushers.set(lessonId, flush)
  return () => {
    if (flushers.get(lessonId) === flush) flushers.delete(lessonId)
  }
}

export async function releaseEditor(lessonId: number): Promise<void> {
  await flushers.get(lessonId)?.()
}
