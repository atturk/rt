/**
 * Mappatura deterministica e coerente dei colori delle materie nel calendario (var(--m1)..var(--m7)).
 */
const PALETTE = [
  'var(--m1)',
  'var(--m2)',
  'var(--m3)',
  'var(--m4)',
  'var(--m5)',
  'var(--m6)',
  'var(--m7)',
]

export function getSubjectColor(materia?: string): string {
  if (!materia) return PALETTE[0]
  const upper = materia.trim().toUpperCase()
  let hash = 0
  for (let i = 0; i < upper.length; i++) {
    hash = (hash * 31 + upper.charCodeAt(i)) >>> 0
  }
  return PALETTE[hash % PALETTE.length]
}
