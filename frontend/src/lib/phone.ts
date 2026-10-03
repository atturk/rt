import { useSyncExternalStore } from 'react'

/** Stesso limite di Tailwind (max-md): sotto i 768 px è il layout del telefono. */
const QUERY = '(max-width: 767.98px)'

function subscribe(onChange: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined
  const media = window.matchMedia(QUERY)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

function snapshot() {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(QUERY).matches
}

/**
 * true sul telefono. Serve dove i due layout hanno controlli diversi (barra a icone o schede in
 * basso, Raggruppa o Raggruppa e ordina): se ne monta uno solo, così i nomi accessibili non si
 * ripetono nel DOM.
 */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}
