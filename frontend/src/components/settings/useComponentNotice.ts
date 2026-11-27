import { useComponents, type ComponentStatus } from '@/api/components'

/** Restituisce il componente necessario al motore effettivo se non è né pronto né in download. */
export function computeMissingTranscriptionComponent(
  items: ComponentStatus[] | undefined,
): ComponentStatus | null {
  if (!Array.isArray(items)) return null
  const required = items.find((c) => c.required && c.available)
  if (!required) return null
  if (required.state === 'ready' || required.state === 'downloading') return null
  return required
}

export function useComponentNotice() {
  const { data } = useComponents()
  const missing = computeMissingTranscriptionComponent(Array.isArray(data) ? data : undefined)
  return {
    missing,
    label: missing ? `${missing.name} da scaricare` : null,
  }
}
