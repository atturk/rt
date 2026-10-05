/** Velocità del player: preferenza dell'interfaccia con copia locale delle preferenze RT, uguale in lezione e revisione. */

export const RATE_MIN = 0.5
export const RATE_MAX = 3
export const RATE_STEP = 0.05
const KEY = 'rt-pref:audio.rate'

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
    return raw == null ? 1 : clampRate(Number(JSON.parse(raw)))
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

/** Velocità del pulsante della barra audio (design 4.2): valori fissi, un clic passa al successivo. */
export const SPEEDS = [1, 1.25, 1.5, 1.75, 2] as const

/** Velocità dopo un clic: la prima dei valori fissi sopra quella attuale, dopo 2× si torna a 1×.
 * Una velocità salvata dal vecchio slider (per esempio 1,15×) passa al valore fisso successivo. */
export function nextSpeed(rate: number): number {
  return SPEEDS.find((speed) => speed > rate + 0.001) ?? SPEEDS[0]
}

/** "1,25×": la virgola italiana del design. */
export function formatSpeed(rate: number): string {
  return `${String(clampRate(rate)).replace('.', ',')}×`
}
