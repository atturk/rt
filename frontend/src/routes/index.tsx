import type { RouteObject } from 'react-router'

import { Layout } from '@/components/Layout'
import { LoginPage } from './auth'
import { jobsArea } from './jobs'
import { lessonsArea } from './lessons'
import type { Area } from './types'

/** Ogni area aggiunge le sue rotte e voci di menu nel proprio file (routes/<area>.tsx). */
export const areas: Area[] = [lessonsArea, jobsArea]

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  { path: '/', element: <Layout areas={areas} />, children: areas.flatMap((a) => a.routes) },
  { path: '*', element: <NotFound /> },
]

function NotFound() {
  return (
    <main className="p-8 text-sm">
      Pagina non trovata. <a href="/" className="underline">Torna alle lezioni</a>
    </main>
  )
}
