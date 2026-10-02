import type { RouteObject } from 'react-router'

/** Una area della SPA: le sue rotte (sotto il layout autenticato). */
export type Area = {
  routes: RouteObject[]
}
