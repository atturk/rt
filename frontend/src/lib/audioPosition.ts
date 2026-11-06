export type AudioPlayerPosition = 'bottom' | 'left' | 'right'

export const AUDIO_POS_KEY = 'rt-device:audio-pos'

export function getAudioPosition(): AudioPlayerPosition {
  if (typeof localStorage === 'undefined') return 'bottom'
  try {
    const val = localStorage.getItem(AUDIO_POS_KEY) || localStorage.getItem('rt-audio-pos')
    if (val === 'left' || val === 'right' || val === 'bottom') return val
  } catch {
    return 'bottom'
  }
  return 'bottom'
}

export function setAudioPosition(pos: AudioPlayerPosition): void {
  try {
    localStorage.setItem(AUDIO_POS_KEY, pos)
    localStorage.setItem('rt-audio-pos', pos)
  } catch {
    // ignore
  }
}

export function isLateralAllowed(isPhone: boolean = false): boolean {
  if (typeof window === 'undefined') return false
  if (isPhone) return false
  if (window.matchMedia?.('(max-width: 767.98px)').matches) return false
  return (window.innerWidth || 1200) >= 900
}
