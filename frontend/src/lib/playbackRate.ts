/** Velocità del player: preferenza dell'interfaccia salvata nel browser, uguale in lezione e revisione. */

export const RATE_MIN = 0.5
export const RATE_MAX = 3
export const RATE_STEP = 0.05
const KEY = 'rt-playback-rate'

/** Porta un valore qualsiasi nell'intervallo, a passi di 0.05 (1 se non è un numero). */
export function clampRate(value: number): number {
  if (!Number.isFinite(value)) return 1
  const stepped = Math.round(value / RATE_STEP) * RATE_STEP
  return Number(Math.min(RATE_MAX, Math.max(RATE_MIN, stepped)).toFixed(2))
}

export function formatRate(rate: number): string {
  return `${clampRate(rate)}×`
}

export function loadRate(storage: Pick<Storage, 'getItem'> | undefined = globalThis.localStorage): number {
  try {
    const raw = storage?.getItem(KEY)
    return raw == null ? 1 : clampRate(Number(raw))
  } catch {
    return 1
  }
}

export function saveRate(rate: number, storage: Pick<Storage, 'setItem'> | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(KEY, String(clampRate(rate)))
  } catch {
    /* archiviazione non disponibile: la velocità vale solo per questa pagina */
  }
}
