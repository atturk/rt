import { lazy, Suspense, type ComponentType } from 'react'
import { Navigate, type RouteObject } from 'react-router'

import { Layout } from '@/components/Layout'
import { SetupGate } from './setupGate'
import type { Area } from './types'

/**
 * Le pagine di ogni area stanno in routes/<area>.tsx e si caricano solo quando servono (un
 * chunk per area, React.lazy): qui restano le rotte, che servono subito. Il menu (design 4.2)
 * ha solo Nuova lezione, Lezioni, Job in corso e Impostazioni (components/Layout.tsx): le altre
 * pagine restano raggiungibili dall'URL e dai link nelle pagine. `handle.bare` = pagina con la
 * sua intestazione a tutta larghezza (design 4.2).
 * Il layout si mostra senza aspettare il chunk: l'attesa è il Suspense attorno al suo Outlet.
 */
function page<M>(load: () => Promise<M>, pick: (module: M) => ComponentType): ComponentType {
  return lazy(async () => ({ default: pick(await load()) }))
}

const lessons = () => import('./lessons')
const jobs = () => import('./jobs')
const recall = () => import('./recall')
const images = () => import('./images')
const settings = () => import('./settings')

const bare = { bare: true }

const lessonsArea: Area = {
  routes: [
    { index: true, Component: page(lessons, (m) => m.DashboardPage), handle: bare },
    { path: 'lezioni/nuova/:jobId', Component: page(lessons, (m) => m.NewLessonPage), handle: bare },
    { path: 'lezioni/:lessonId', Component: page(lessons, (m) => m.LessonPage), handle: bare },
    { path: 'lezioni/:lessonId/rilevanza', Component: page(() => import('./relevance'), (m) => m.RelevancePage) },
  ],
}

const jobsArea: Area = {
  routes: [
    { path: 'importa', Component: page(jobs, (m) => m.ImportPage) },
    { path: 'job', Component: page(jobs, (m) => m.JobsPage), handle: bare },
    { path: 'job/:jobId', Component: page(jobs, (m) => m.JobPage), handle: bare },
    { path: 'lezioni/:lessonId/outline', Component: page(jobs, (m) => m.OutlinePage) },
  ],
}

const reviewsArea: Area = {
  routes: [{ path: 'review', Component: page(() => import('./reviews'), (m) => m.ReviewsPage) }],
}

const reviewArea: Area = {
  routes: [{ path: 'lezioni/:lessonId/revisione', Component: page(() => import('./review'), (m) => m.ReviewPage) }],
}

const recallArea: Area = {
  routes: [
    { path: 'recall', Component: page(recall, (m) => m.RecallOverviewPage) },
    { path: 'recall/materie/:materia', Component: page(recall, (m) => m.SubjectRecallPage) },
    { path: 'recall/giorno/:day', Component: page(recall, (m) => m.SubjectRecallPage) },
    { path: 'lezioni/:lessonId/recall', Component: page(recall, (m) => m.RecallPage) },
    { path: 'lezioni/:lessonId/recall/domande', Component: page(recall, (m) => m.QuestionsPage) },
  ],
}

const imagesArea: Area = {
  routes: [
    { path: 'arricchimento', Component: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/arricchimento', Component: page(images, (m) => m.ImagesPage) },
    { path: 'immagini', Component: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/immagini', Component: page(images, (m) => m.ImagesPage) },
  ],
}

const settingsArea: Area = {
  routes: [
    { path: 'impostazioni/configurazione', Component: page(settings, (m) => m.SetupWizardPage) },
    {
      path: 'impostazioni',
      Component: page(settings, (m) => m.SettingsLayout),
      handle: bare,
      children: [
        { index: true, Component: page(settings, (m) => m.GeneralSettingsPage) },
        { path: 'modelli', Component: page(settings, (m) => m.ModelsSettingsPage) },
        { path: 'chiavi', Component: page(settings, (m) => m.KeysSettingsPage) },
        { path: 'costi', Component: page(settings, (m) => m.CostsSettingsPage) },
        { path: 'ricerca-web', Component: page(settings, (m) => m.WebSearchSettingsPage) },
        { path: 'decisioni', Component: page(settings, (m) => m.DecisionsSettingsPage) },
        { path: 'info', Component: page(settings, (m) => m.InfoSettingsPage) },
        // Bot Telegram (RT4-FA6): nel design 4.2 sta nelle impostazioni; /bot resta valido.
        { path: 'bot', Component: page(() => import('./telegram'), (m) => m.TelegramPage) },
      ],
    },
    { path: 'bot', element: <Navigate to="/impostazioni/bot" replace /> },
  ],
}

export const areas: Area[] = [lessonsArea, jobsArea, reviewsArea, reviewArea, recallArea, imagesArea, settingsArea]

const LoginPage = page(() => import('./auth'), (m) => m.LoginPage)

export const routes: RouteObject[] = [
  {
    path: '/login',
    element: (
      <Suspense fallback={<p className="p-8 text-sm text-muted-foreground">Carico…</p>}>
        <LoginPage />
      </Suspense>
    ),
  },
  {
    path: '/',
    element: <Layout />,
    // SetupGate porta alla configurazione guidata se il backend segnala setup_required (RT4-F5).
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
