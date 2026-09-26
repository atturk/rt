import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'

/** Una area della SPA: le sue rotte (sotto il layout autenticato), se serve voci di menu e un
 * elemento nell'intestazione (es. il pannello dei job). */
export type Area = {
  routes: RouteObject[]
  nav?: { to: string; label: string; icon: LucideIcon; end?: boolean }[]
  header?: ComponentType
}
