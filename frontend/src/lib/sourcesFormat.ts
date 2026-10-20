import type { SourceItem } from '@/api/sources'

export function formatSourceDuration(seconds?: number | null): string {
  if (seconds == null) return ''
  const m = Math.round(seconds / 60)
  const h = Math.floor(m / 60)
  const remMin = m % 60
  if (h > 0) {
    return remMin > 0 ? `${h} h ${remMin} min` : `${h} h`
  }
  return `${m} min`
}

export function formatSourceSize(source: SourceItem): string {
  if (source.tipo === 'audio') return formatSourceDuration(source.durata_s)
  if (source.tipo === 'appunti') {
    return source.parole != null ? `${new Intl.NumberFormat('it-IT').format(source.parole)} parole` : ''
  }
  if (source.tipo === 'materiale') {
    return source.pagine_totali != null ? `${source.pagine_totali} ${source.pagine_totali === 1 ? 'pagina' : 'pagine'}` : ''
  }
  return ''
}

export function formatVersionDate(isoDate: string): string {
  try {
    const d = new Date(isoDate)
    const now = new Date()
    const isToday =
      d.getDate() === now.getDate() &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear()
    const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    if (isToday) return `Oggi ${time}`
    const months = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']
    return `${d.getDate()} ${months[d.getMonth()]} ${time}`
  } catch {
    return isoDate
  }
}
