import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'

/** Una area della SPA: le sue rotte (sotto il layout autenticato) e, se serve, voci di menu.
 * `badge` si mostra accanto alla voce (es. il numero di job attivi su "Job"). */
export type Area = {
  routes: RouteObject[]
  nav?: { to: string; label: string; icon: LucideIcon; end?: boolean; badge?: ComponentType }[]
}
