export const ZOOM_LEVELS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2] as const

export type ZoomLevel = (typeof ZOOM_LEVELS)[number]

const STORAGE_KEY = 'rt-device:zoom'

export function getZoom(): number {
  if (typeof localStorage === 'undefined') return 1
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = parseFloat(raw)
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed
      }
    }
  } catch {
    return 1
  }
  return 1
}

function findClosestIndex(v: number): number {
  let closest = 0
  let minDiff = Infinity
  for (let i = 0; i < ZOOM_LEVELS.length; i++) {
    const diff = Math.abs(ZOOM_LEVELS[i] - v)
    if (diff < minDiff) {
      minDiff = diff
      closest = i
    }
  }
  return closest
}

export function setZoom(v: number): void {
  const min = ZOOM_LEVELS[0]
  const max = ZOOM_LEVELS[ZOOM_LEVELS.length - 1]
  const clamped = Math.max(min, Math.min(max, v))

  try {
    localStorage.setItem(STORAGE_KEY, String(clamped))
  } catch {
    // Continua anche se localStorage fallisce
  }

  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.style.zoom = String(clamped)
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('rt-zoom-change', { detail: { zoom: clamped } }))
  }
}

export function zoomIn(): void {
  const current = getZoom()
  const idx = findClosestIndex(current)
  if (idx < ZOOM_LEVELS.length - 1) {
    setZoom(ZOOM_LEVELS[idx + 1])
  } else {
    setZoom(ZOOM_LEVELS[ZOOM_LEVELS.length - 1])
  }
}

export function zoomOut(): void {
  const current = getZoom()
  const idx = findClosestIndex(current)
  if (idx > 0) {
    setZoom(ZOOM_LEVELS[idx - 1])
  } else {
    setZoom(ZOOM_LEVELS[0])
  }
}

export function resetZoom(): void {
  setZoom(1)
}

export function zoomed(px: number): number {
  const z = getZoom()
  return z > 0 ? px / z : px
}

export function isAppWindow(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const search = window.location?.search
    if (search && new URLSearchParams(search).get('app') === '1') {
      sessionStorage.setItem('rt-app', '1')
      return true
    }
    // La finestra dell'app (pywebview) espone window.pywebview; il redirect di /login perde ?app=1.
    return sessionStorage.getItem('rt-app') === '1' || 'pywebview' in window
  } catch {
    return false
  }
}

export function handleZoomKeydown(e: KeyboardEvent): boolean {
  if (!isAppWindow()) return false
  if (!e.metaKey && !e.ctrlKey) return false
  if (e.altKey) return false

  const isPlus = e.key === '+' || e.key === '=' || e.code === 'NumpadAdd'
  const isMinus = e.key === '-' || e.code === 'NumpadSubtract'
  const isZero = (e.key === '0' || e.code === 'Numpad0') && !e.shiftKey

  if (isPlus) {
    e.preventDefault()
    zoomIn()
    return true
  }
  if (isMinus) {
    e.preventDefault()
    zoomOut()
    return true
  }
  if (isZero) {
    e.preventDefault()
    resetZoom()
    return true
  }
  return false
}

declare global {
  interface Window {
    rtZoom?: (action: 'in' | 'out' | 'reset') => void
  }
}

if (typeof window !== 'undefined') {
  window.rtZoom = (action: 'in' | 'out' | 'reset') => {
    if (action === 'in') zoomIn()
    else if (action === 'out') zoomOut()
    else if (action === 'reset') resetZoom()
  }
}

export function initZoom(): void {
  if (typeof window === 'undefined') return
  isAppWindow()
  const current = getZoom()
  if (document.documentElement) {
    document.documentElement.style.zoom = String(current)
  }
  window.removeEventListener('keydown', handleZoomKeydown)
  window.addEventListener('keydown', handleZoomKeydown)
}
