const MIME_EXTENSIONS: [string, string][] = [
  ['audio/webm', 'webm'],
  ['audio/ogg', 'ogg'],
  ['audio/mp4', 'm4a'],
]

/** Formato registrabile dal browser e l'estensione che l'API accetta per le risposte vocali. */
export function recordingFormat(isSupported: (type: string) => boolean): { mimeType?: string; extension: string } {
  for (const [mimeType, extension] of MIME_EXTENSIONS) {
    if (isSupported(mimeType)) return { mimeType, extension }
  }
  return { extension: 'webm' }
}
