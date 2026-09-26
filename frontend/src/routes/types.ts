import type { LucideIcon } from 'lucide-react'
import type { RouteObject } from 'react-router'

/** Una area della SPA: le sue rotte (sotto il layout autenticato) e, se serve, una voce di menu. */
export type Area = {
  routes: RouteObject[]
  nav?: { to: string; label: string; icon: LucideIcon; end?: boolean }[]
}
