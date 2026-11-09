export const STUDY_AUDIO_OPEN_KEY = 'rt-device:study-audio-open'

export function getStudyAudioOpen(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return localStorage.getItem(STUDY_AUDIO_OPEN_KEY) === 'true'
  } catch {
    return false
  }
}

export function setStudyAudioOpen(open: boolean): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STUDY_AUDIO_OPEN_KEY, String(open))
  } catch {
    // ignore
  }
}

export function resetStudyAudioOpen(): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(STUDY_AUDIO_OPEN_KEY)
  } catch {
    // ignore
  }
}
