/** Campo numerico "Immagini per unità": stato come stringa durante la digitazione,
 *  validazione al salvataggio. */

export const PER_UNIT_MIN = 0
export const PER_UNIT_MAX = 10

/** Ripulisce il testo mentre si digita: niente zeri iniziali ("03" diventa "3"), il campo
 *  si può svuotare. Il resto (lettere, segni) si segnala al salvataggio. */
export function normalizeCountInput(raw: string): string {
  const trimmed = raw.trim()
  return /^\d+$/.test(trimmed) ? trimmed.replace(/^0+(?=\d)/, '') : trimmed
}

export type CountResult = { ok: true; value: number } | { ok: false; error: string }

/** Valore da salvare: vuoto vale 0; un intero fra min e max, altrimenti l'errore da mostrare. */
export function parseCount(raw: string, min = PER_UNIT_MIN, max = PER_UNIT_MAX): CountResult {
  const text = raw.trim()
  if (text === '') return { ok: true, value: min }
  if (!/^\d+$/.test(text)) return { ok: false, error: `Scrivi un numero intero da ${min} a ${max}.` }
  const value = Number(text)
  if (value < min || value > max) return { ok: false, error: `Scrivi un numero da ${min} a ${max}.` }
  return { ok: true, value }
}
