/**
 * fetch per openapi-fetch basato su XMLHttpRequest, solo per gli upload: fetch non espone
 * l'avanzamento dell'invio. La richiesta resta quella del client generato (percorso tipizzato,
 * header CSRF del middleware); qui cambia solo il trasporto.
 */
export type UploadProgress = { loaded: number; total: number | null }

function parseHeaders(raw: string): Headers {
  const headers = new Headers()
  for (const line of raw.trim().split(/[\r\n]+/)) {
    const at = line.indexOf(':')
    if (at > 0) headers.append(line.slice(0, at).trim(), line.slice(at + 1).trim())
  }
  return headers
}

export function xhrFetch(body: XMLHttpRequestBodyInit, onProgress: (progress: UploadProgress) => void) {
  return (request: Request) =>
    new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open(request.method, request.url)
      xhr.withCredentials = true
      request.headers.forEach((value, key) => {
        // il browser mette da solo Content-Type con il boundary del multipart
        if (key.toLowerCase() !== 'content-type') xhr.setRequestHeader(key, value)
      })
      xhr.upload.onprogress = (e) => onProgress({ loaded: e.loaded, total: e.lengthComputable ? e.total : null })
      xhr.onload = () =>
        resolve(new Response(xhr.status === 204 ? null : xhr.responseText, { status: xhr.status, headers: parseHeaders(xhr.getAllResponseHeaders()) }))
      xhr.onerror = () => reject(new TypeError('Rete non raggiungibile'))
      xhr.onabort = () => reject(new DOMException('Caricamento annullato', 'AbortError'))
      request.signal?.addEventListener('abort', () => xhr.abort())
      xhr.send(body)
    })
}
