/**
 * Unico punto di scaricamento e salvataggio file dell'applicazione.
 */

/** Scarica un file esportato dall'API usando fetch autenticato (stessa sessione). */
export async function fetchExport(url: string, fallbackName?: string): Promise<File> {
  const response = await fetch(url, { credentials: 'same-origin' })
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
