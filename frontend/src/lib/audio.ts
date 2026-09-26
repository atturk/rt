export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const whole = Math.floor(seconds)
  const h = Math.floor(whole / 3600)
  const m = Math.floor(whole / 60) % 60
  const s = String(whole % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export type TimedSection = { unit_id: string; start_seconds?: number | null }

/** Unità in ascolto: quella iniziata più di recente prima di t (null prima della prima). */
export function activeUnit(sections: TimedSection[], t: number): string | null {
  let current: string | null = null
  let best = -Infinity
  for (const s of sections) {
    const start = s.start_seconds
    if (start == null || start > t || start < best) continue
    best = start
    current = s.unit_id
  }
  return current
}

/** Inizio dell'unità precedente o successiva rispetto a t (per i pulsanti ◀◀ ▶▶). */
export function neighbourStart(sections: TimedSection[], t: number, direction: -1 | 1): number | null {
  const starts = [...new Set(sections.map((s) => s.start_seconds).filter((v): v is number => v != null))].sort((a, b) => a - b)
  if (direction === 1) return starts.find((s) => s > t + 0.5) ?? null
  // indietro: se sei a pochi secondi dall'inizio dell'unità vai alla precedente, come i lettori audio
  const before = starts.filter((s) => s < t - 2)
  return before.length ? before[before.length - 1] : starts.length ? starts[0] : null
}
