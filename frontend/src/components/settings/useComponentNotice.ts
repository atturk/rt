import { useComponents, type ComponentStatus } from '@/api/components'

export function isComponentMissing(c: ComponentStatus): boolean {
  return c.required && c.available && c.state !== 'ready' && c.state !== 'downloading'
}

/** Restituisce tutti i componenti necessari (trascrizione e browser) non pronti e non in download. */
export function computeMissingComponents(
  items: ComponentStatus[] | undefined,
): ComponentStatus[] {
  if (!Array.isArray(items)) return []
  return items.filter(isComponentMissing)
}

export function useComponentNotice() {
  const { data } = useComponents()
  const missing = computeMissingComponents(Array.isArray(data) ? data : undefined)
  const label =
    missing.length === 0
      ? null
      : missing.length === 1
        ? `${missing[0].name} da scaricare`
        : 'Componenti da scaricare'
  return {
    missing,
    label,
  }
}
