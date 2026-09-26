import type { RouteObject } from 'react-router'

import { Layout } from '@/components/Layout'
import { LoginPage } from './auth'
import { imagesArea } from './images'
import { lessonsArea } from './lessons'
import { recallArea } from './recall'
import { reviewArea } from './review'
import { SetupGate, settingsArea } from './settings'
import { telegramArea } from './telegram'
import type { Area } from './types'

/** Ogni area aggiunge le sue rotte e voci di menu nel proprio file (routes/<area>.tsx). */
export const areas: Area[] = [lessonsArea, reviewArea, recallArea, imagesArea, telegramArea, settingsArea]

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <Layout areas={areas} />,
    // SetupGate porta alla configurazione guidata finché la cartella dati non è impostata (RT4-F5).
    children: [{ element: <SetupGate />, children: areas.flatMap((a) => a.routes) }],
  },
  { path: '*', element: <NotFound /> },
]

function NotFound() {
  return (
    <main className="p-8 text-sm">
      Pagina non trovata. <a href="/" className="underline">Torna alle lezioni</a>
    </main>
  )
}
