const ACCEPTED_EXTENSIONS = new Set([
  '.mp3',
  '.m4a',
  '.wav',
  '.aac',
  '.ogg',
  '.flac',
  '.wma',
  '.opus',
  '.pdf',
  '.pptx',
  '.docx',
  '.txt',
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.zip',
])

export function isAcceptedFile(file: File): boolean {
  const dot = file.name.lastIndexOf('.')
  if (dot === -1) return false
  const ext = file.name.slice(dot).toLowerCase()
  return ACCEPTED_EXTENSIONS.has(ext)
}

export function hasAcceptedDrag(dt: DataTransfer): boolean {
  const types = Array.from(dt.types ?? [])
  if (!types.includes('Files')) return false

  // Se i file sono già accessibili (es. evento sintetico o Playwright)
  if (dt.files && dt.files.length > 0) {
    return Array.from(dt.files).some(isAcceptedFile)
  }

  // Altrimenti controlla items
  if (dt.items && dt.items.length > 0) {
    let hasFile = false
    for (let i = 0; i < dt.items.length; i++) {
      const item = dt.items[i]
      if (item.kind !== 'file') return false
      hasFile = true
      if (item.type) {
        const t = item.type.toLowerCase()
        const isAudio = t.startsWith('audio/')
        const isImage =
          t.startsWith('image/png') ||
          t.startsWith('image/jpeg') ||
          t.startsWith('image/webp')
        const isDoc =
          t === 'application/pdf' ||
          t.includes('wordprocessingml') ||
          t.includes('presentationml') ||
          t === 'text/plain'
        const isZip = t === 'application/zip' || t.includes('zip')
        if (!isAudio && !isImage && !isDoc && !isZip) {
          return false
        }
      }
    }
    return hasFile
  }

  return true
}

export function isExcludedTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false
  return !!target.closest(
    '[data-file-drop-target], .cm-editor, .cm-content, [data-panel="dettagli"], [data-testid="lesson-details"], [data-testid="sources-section"], [data-testid="drop-zone"], [data-testid="chosen-files"]',
  )
}
