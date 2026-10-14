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

export type SpeechSection = {
  unit_id: string
  start_seconds?: number | null
  end_seconds?: number | null
  speech_segments?: [number, number][] | number[][] | null
}

/**
 * AU1: calcola l'avanzamento della linea audio contando solo il parlato.
 * Le pause o i tratti senza trascritto non fanno avanzare la linea.
 */
export function unitSpeechProgress(
  section: SpeechSection,
  currentTime: number,
): { cur: boolean; done: boolean; percent: number } {
  const start = section.start_seconds ?? 0
  const end = section.end_seconds ?? start
  if (currentTime < start) return { cur: false, done: false, percent: 0 }
  if (currentTime >= end) return { cur: false, done: true, percent: 100 }
  const cur = true
  const segments = section.speech_segments
  if (segments && segments.length > 0) {
    let totalSpeech = 0
    let spoken = 0
    for (const seg of segments) {
      const sStart = seg[0]
      const sEnd = seg[1]
      if (sStart == null || sEnd == null) continue
      const dur = Math.max(0, sEnd - sStart)
      totalSpeech += dur
      if (currentTime > sStart) {
        spoken += Math.max(0, Math.min(currentTime, sEnd) - sStart)
      }
    }
    if (totalSpeech > 0) {
      const p = Math.min(100, Math.max(0, (spoken / totalSpeech) * 100))
      return { cur, done: false, percent: p }
    }
  }
  const dur = end - start
  const p = dur > 0 ? Math.min(100, Math.max(0, ((currentTime - start) / dur) * 100)) : 100
  return { cur, done: false, percent: p }
}
