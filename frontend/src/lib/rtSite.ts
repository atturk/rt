import { encode } from 'uqr'

/**
 * Sito pubblico di RT: landing page e download. È il link del QR nella prima pagina dei PDF
 * esportati. Per cambiare sito (es. un dominio personalizzato) basta cambiare questo valore.
 */
export const RT_SITE_URL = 'https://atturk.github.io/rt/'

/** L'URL da mostrare sotto il QR: senza protocollo, «www.» e barra finale. */
export function rtSiteLabel(url: string = RT_SITE_URL): string {
  return url.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/+$/, '')
}

const POSITION = 2

/**
 * QR personalizzato col logo di RT al centro: moduli tondi, occhi arrotondati, nero su bianco
 * perché lo leggano anche le stampanti in bianco e nero. La correzione H (30%) copre il logo;
 * sotto il logo si tolgono solo moduli di dati, mai quelli di posizione, allineamento e formato.
 */
export function buildRtQr(value: string) {
  const qr = encode(value, { ecc: 'H', border: 0 })
  const { size } = qr
  // Logo di circa un quinto del lato, con un modulo di margine bianco attorno.
  const logo = Math.max(5, Math.round(size * 0.22) | 1)
  const clearFrom = (size - logo) / 2 - 1
  const clearTo = clearFrom + logo + 2
  const inLogo = (x: number, y: number) => x >= clearFrom && x < clearTo && y >= clearFrom && y < clearTo
  const r = 0.45
  const dots: string[] = []
  qr.data.forEach((row, y) => row.forEach((dark, x) => {
    if (!dark || qr.types[y][x] === POSITION) return
    if (qr.types[y][x] === 0 && inLogo(x, y)) return
    dots.push(`M${x + 0.5 - r} ${y + 0.5}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`)
  }))
  const eyes: Array<[number, number]> = [[0, 0], [size - 7, 0], [0, size - 7]]
  return { size, path: dots.join(''), eyes, logo, logoAt: (size - logo) / 2 }
}
