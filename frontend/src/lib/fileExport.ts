/**
 * Unico punto di scaricamento e salvataggio file dell'applicazione.
 */

/** Scarica un file esportato dall'API usando fetch autenticato (stessa sessione). */
export async function fetchExport(
  url: string,
  options?: string | { fallbackName?: string; signal?: AbortSignal },
): Promise<File> {
  const fallbackName = typeof options === 'string' ? options : options?.fallbackName
  const signal = typeof options === 'object' ? options?.signal : undefined
  const response = await fetch(url, { credentials: 'same-origin', signal })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(body?.error?.message ?? `Export non riuscito (${response.status})`)
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  let filename = ''
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8Match?.[1]) {
    try {
      filename = decodeURIComponent(utf8Match[1])
    } catch {
      filename = utf8Match[1]
    }
  }
  if (!filename) {
    const regularMatch = /filename="?([^";]+)"?/i.exec(disposition)
    if (regularMatch?.[1]) {
      filename = regularMatch[1]
    }
  }
  if (!filename) {
    if (fallbackName) {
      filename = fallbackName
    } else {
      const pathname = url.split('?')[0]
      filename = pathname.split('/').filter(Boolean).pop() ?? 'download'
    }
  }
  const contentType = response.headers.get('content-type') || 'application/octet-stream'
  const blob = await response.blob()
  return new File([blob], filename, { type: contentType })
}

/** Salva un file nel browser tramite blob link temporaneo con revoca ritardata (60s). */
export function saveFile(file: File): void {
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = file.name
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => {
    URL.revokeObjectURL(url)
  }, 60_000)
}

/** Verifica se il sistema o l'app supportano la condivisione di file. */
export function canShareFiles(fileType = 'application/pdf'): boolean {
  if (typeof window !== 'undefined') {
    const pywebview = (window as unknown as { pywebview?: { api?: { condividi?: unknown } } }).pywebview
    if (pywebview?.api?.condividi) {
      return true
    }
  }
  if (typeof navigator !== 'undefined' && typeof navigator.canShare === 'function') {
    try {
      const dummy = new File([''], 'test', { type: fileType })
      if (navigator.canShare({ files: [dummy] })) return true
      if (fileType !== 'application/zip') {
        const zipDummy = new File([''], 'test.rt', { type: 'application/zip' })
        if (navigator.canShare({ files: [zipDummy] })) return true
      }
    } catch {
      return false
    }
  }
  return false
}

/** Condivide un file tramite Web Share API di sistema. */
export async function shareFile(file: File, options?: { title?: string }): Promise<void> {
  if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
    let fileToShare = file
    if (navigator.canShare && !navigator.canShare({ files: [fileToShare] })) {
      if (file.name.endsWith('.rt')) {
        const zipFile = new File([file], file.name, { type: 'application/zip' })
        if (navigator.canShare({ files: [zipFile] })) {
          fileToShare = zipFile
        }
      }
    }
    try {
      await navigator.share({
        files: [fileToShare],
        title: options?.title,
      })
    } catch (err: unknown) {
      const error = err as { name?: string; message?: string }
      if (error?.name === 'AbortError') {
        // L'utente chiude il menu di sistema: nessun messaggio d'errore
        return
      }
      throw err
    }
  }
}

