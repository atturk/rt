/**
 * Preferenze di Studio (evidenziatore e lettura veloce) salvate nel browser.
 * Chiavi e forme dei dati sono fissate per il collegamento con le preferenze di RT.
 */

export interface HighlighterPrefs {
  color: number // 0..4
  arrows: boolean
}

export interface RsvpPrefs {
  wpm: number
  orp: 'prima' | 'bilanciata' | 'dopo'
  pauseMs: number
  comma: boolean
  step: number
  size: number
  sound: boolean
  pitch: number
  dyslexic: boolean
  irlen: null | 'pesca' | 'menta' | 'pergamena'
  noise: null | 'bianco' | 'rosa' | 'marrone'
  noiseVolume: number
}

export const DEFAULT_HIGHLIGHTER_PREFS: HighlighterPrefs = {
  color: 0,
  arrows: true,
}

export const DEFAULT_RSVP_PREFS: RsvpPrefs = {
  wpm: 300,
  orp: 'bilanciata',
  pauseMs: 400,
  comma: false,
  step: 5,
  size: 60,
  sound: true,
  pitch: 1.0,
  dyslexic: false,
  irlen: null,
  noise: null,
  noiseVolume: 0.25,
}

const HIGHLIGHTER_KEY = 'rt-pref:study.highlighter'
const RSVP_KEY = 'rt-pref:study.rsvp'

export function loadHighlighterPrefs(storage: Pick<Storage, 'getItem'> = globalThis.localStorage): HighlighterPrefs {
  try {
    const raw = storage?.getItem(HIGHLIGHTER_KEY) ?? storage?.getItem('study.highlighter')
    if (!raw) return { ...DEFAULT_HIGHLIGHTER_PREFS }
    const parsed = JSON.parse(raw) as Partial<HighlighterPrefs>
    return {
      color: typeof parsed.color === 'number' && parsed.color >= 0 && parsed.color <= 4 ? parsed.color : DEFAULT_HIGHLIGHTER_PREFS.color,
      arrows: typeof parsed.arrows === 'boolean' ? parsed.arrows : DEFAULT_HIGHLIGHTER_PREFS.arrows,
    }
  } catch {
    return { ...DEFAULT_HIGHLIGHTER_PREFS }
  }
}

export function saveHighlighterPrefs(
  prefs: Partial<HighlighterPrefs>,
  storage: Pick<Storage, 'getItem' | 'setItem'> = globalThis.localStorage,
): HighlighterPrefs {
  try {
    const current = loadHighlighterPrefs(storage)
    const merged: HighlighterPrefs = {
      color: typeof prefs.color === 'number' && prefs.color >= 0 && prefs.color <= 4 ? prefs.color : current.color,
      arrows: typeof prefs.arrows === 'boolean' ? prefs.arrows : current.arrows,
    }
    storage?.setItem(HIGHLIGHTER_KEY, JSON.stringify(merged))
    return merged
  } catch {
    return { ...DEFAULT_HIGHLIGHTER_PREFS, ...prefs }
  }
}

export function loadRsvpPrefs(storage: Pick<Storage, 'getItem'> = globalThis.localStorage): RsvpPrefs {
  try {
    const raw = storage?.getItem(RSVP_KEY) ?? storage?.getItem('study.rsvp')
    if (!raw) return { ...DEFAULT_RSVP_PREFS }
    const parsed = JSON.parse(raw) as Partial<RsvpPrefs>
    return {
      wpm: typeof parsed.wpm === 'number' && parsed.wpm >= 100 && parsed.wpm <= 900 ? parsed.wpm : DEFAULT_RSVP_PREFS.wpm,
      orp: parsed.orp === 'prima' || parsed.orp === 'bilanciata' || parsed.orp === 'dopo' ? parsed.orp : DEFAULT_RSVP_PREFS.orp,
      pauseMs: typeof parsed.pauseMs === 'number' && parsed.pauseMs >= 0 && parsed.pauseMs <= 1200 ? parsed.pauseMs : DEFAULT_RSVP_PREFS.pauseMs,
      comma: typeof parsed.comma === 'boolean' ? parsed.comma : DEFAULT_RSVP_PREFS.comma,
      step: typeof parsed.step === 'number' ? parsed.step : DEFAULT_RSVP_PREFS.step,
      size: typeof parsed.size === 'number' ? parsed.size : DEFAULT_RSVP_PREFS.size,
      sound: typeof parsed.sound === 'boolean' ? parsed.sound : DEFAULT_RSVP_PREFS.sound,
      pitch: typeof parsed.pitch === 'number' ? parsed.pitch : DEFAULT_RSVP_PREFS.pitch,
      dyslexic: typeof parsed.dyslexic === 'boolean' ? parsed.dyslexic : DEFAULT_RSVP_PREFS.dyslexic,
      irlen: parsed.irlen === 'pesca' || parsed.irlen === 'menta' || parsed.irlen === 'pergamena' ? parsed.irlen : null,
      noise: parsed.noise === 'bianco' || parsed.noise === 'rosa' || parsed.noise === 'marrone' ? parsed.noise : null,
      noiseVolume: typeof parsed.noiseVolume === 'number' ? parsed.noiseVolume : DEFAULT_RSVP_PREFS.noiseVolume,
    }
  } catch {
    return { ...DEFAULT_RSVP_PREFS }
  }
}

export function saveRsvpPrefs(
  prefs: Partial<RsvpPrefs>,
  storage: Pick<Storage, 'getItem' | 'setItem'> = globalThis.localStorage,
): RsvpPrefs {
  try {
    const current = loadRsvpPrefs(storage)
    const merged: RsvpPrefs = {
      ...current,
      ...prefs,
    }
    storage?.setItem(RSVP_KEY, JSON.stringify(merged))
    return merged
  } catch {
    return { ...DEFAULT_RSVP_PREFS, ...prefs }
  }
}
