import { useMemo } from 'react'

import { buildRtQr, RT_SITE_URL, rtSiteLabel } from '@/lib/rtSite'

/** Il QR che porta al sito di RT, con l'URL leggibile accanto (prima pagina dei PDF). */
export function RtSiteQr({ url = RT_SITE_URL }: { url?: string }) {
  const qr = useMemo(() => buildRtQr(url), [url])
  const { size, logo, logoAt } = qr
  const s = logo / 32 // il logo è disegnato su 32 unità come la favicon
  return (
    <a className="print-rt-qr" href={url} data-testid="rt-site-qr">
      <svg role="img" aria-label={`QR per il sito di RT: ${url}`} viewBox={`-1 -1 ${size + 2} ${size + 2}`}>
        <rect x={-1} y={-1} width={size + 2} height={size + 2} fill="#fff" />
        <path d={qr.path} fill="#000" />
        {qr.eyes.map(([x, y]) => (
          <g key={`${x}-${y}`}>
            <rect x={x + 0.5} y={y + 0.5} width={6} height={6} rx={1.6} fill="none" stroke="#000" strokeWidth={1} />
            <rect x={x + 2} y={y + 2} width={3} height={3} rx={0.8} fill="#000" />
          </g>
        ))}
        <g transform={`translate(${logoAt} ${logoAt}) scale(${s})`}>
          <rect width={32} height={32} rx={7} fill="#171717" />
          <text x={7} y={23} fontFamily="Helvetica,Arial,sans-serif" fontSize={19} fontWeight={700} fill="#fff">rt</text>
          <circle cx={26} cy={21} r={2.4} fill="#19a07f" />
        </g>
      </svg>
      <span className="print-rt-qr-label">
        <span>Rielaborato con RT</span>
        <span className="print-rt-qr-url">{rtSiteLabel(url)}</span>
      </span>
    </a>
  )
}
