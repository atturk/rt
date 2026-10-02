import { Activity, Bot, Brain, ClipboardCheck, Images, LayoutDashboard, Settings as SettingsIcon, Upload } from 'lucide-react'
import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'

import { JobsNavBadge } from '@/components/jobs/JobsIndicator'
import { Layout } from '@/components/Layout'
import { SetupGate } from './setupGate'
import type { Area } from './types'

/**
 * Le pagine di ogni area stanno in routes/<area>.tsx e si caricano solo quando servono (un
 * chunk per area): qui restano le rotte e le voci di menu, che servono subito.
 */
function page<M>(load: () => Promise<M>, pick: (module: M) => ComponentType): RouteObject['lazy'] {
  return async () => ({ Component: pick(await load()) })
}

const lessons = () => import('./lessons')
const jobs = () => import('./jobs')
const recall = () => import('./recall')
const images = () => import('./images')
const settings = () => import('./settings')

const lessonsArea: Area = {
  routes: [
    { index: true, lazy: page(lessons, (m) => m.DashboardPage) },
    { path: 'lezioni/:lessonId', lazy: page(lessons, (m) => m.LessonPage) },
    { path: 'lezioni/:lessonId/rilevanza', lazy: page(() => import('./relevance'), (m) => m.RelevancePage) },
  ],
  nav: [{ to: '/', label: 'Lezioni', icon: LayoutDashboard, end: true }],
}

const jobsArea: Area = {
  routes: [
    { path: 'importa', lazy: page(jobs, (m) => m.ImportPage) },
    { path: 'job', lazy: page(jobs, (m) => m.JobsPage) },
    { path: 'job/:jobId', lazy: page(jobs, (m) => m.JobPage) },
    { path: 'lezioni/:lessonId/outline', lazy: page(jobs, (m) => m.OutlinePage) },
  ],
  nav: [
    { to: '/importa', label: 'Importa', icon: Upload },
    { to: '/job', label: 'Job', icon: Activity, badge: JobsNavBadge },
  ],
}

const reviewsArea: Area = {
  routes: [{ path: 'review', lazy: page(() => import('./reviews'), (m) => m.ReviewsPage) }],
  nav: [{ to: '/review', label: 'Review', icon: ClipboardCheck }],
}

const reviewArea: Area = {
  routes: [{ path: 'lezioni/:lessonId/revisione', lazy: page(() => import('./review'), (m) => m.ReviewPage) }],
}

const recallArea: Area = {
  routes: [
    { path: 'recall', lazy: page(recall, (m) => m.RecallOverviewPage) },
    { path: 'recall/materie/:materia', lazy: page(recall, (m) => m.SubjectRecallPage) },
    { path: 'recall/giorno/:day', lazy: page(recall, (m) => m.SubjectRecallPage) },
    { path: 'lezioni/:lessonId/recall', lazy: page(recall, (m) => m.RecallPage) },
    { path: 'lezioni/:lessonId/recall/domande', lazy: page(recall, (m) => m.QuestionsPage) },
  ],
  nav: [{ to: '/recall', label: 'Recall', icon: Brain }],
}

const imagesArea: Area = {
  routes: [
    { path: 'arricchimento', lazy: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/arricchimento', lazy: page(images, (m) => m.ImagesPage) },
    { path: 'immagini', lazy: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/immagini', lazy: page(images, (m) => m.ImagesPage) },
  ],
  nav: [{ to: '/arricchimento', label: 'Arricchimento', icon: Images }],
}

/** Il pannello di avvio sta anche nelle impostazioni (RT4-F5); qui la pagina completa (RT4-FA6). */
const telegramArea: Area = {
  routes: [{ path: 'bot', lazy: page(() => import('./telegram'), (m) => m.TelegramPage) }],
  nav: [{ to: '/bot', label: 'Bot Telegram', icon: Bot }],
}

const settingsArea: Area = {
  routes: [
    { path: 'impostazioni/configurazione', lazy: page(settings, (m) => m.SetupWizardPage) },
    {
      path: 'impostazioni',
      lazy: page(settings, (m) => m.SettingsLayout),
      children: [
        { index: true, lazy: page(settings, (m) => m.GeneralSettingsPage) },
        { path: 'modelli', lazy: page(settings, (m) => m.ModelsSettingsPage) },
        { path: 'chiavi', lazy: page(settings, (m) => m.KeysSettingsPage) },
        { path: 'costi', lazy: page(settings, (m) => m.CostsSettingsPage) },
        { path: 'ricerca-web', lazy: page(settings, (m) => m.WebSearchSettingsPage) },
        { path: 'decisioni', lazy: page(settings, (m) => m.DecisionsSettingsPage) },
        { path: 'info', lazy: page(settings, (m) => m.InfoSettingsPage) },
      ],
    },
  ],
  nav: [{ to: '/impostazioni', label: 'Impostazioni', icon: SettingsIcon }],
}

export const areas: Area[] = [lessonsArea, jobsArea, reviewsArea, reviewArea, recallArea, imagesArea, telegramArea, settingsArea]

/** Mentre arriva il chunk della prima pagina: lo stesso "Carico…" del layout in attesa di /me. */
function Loading() {
  return <p className="p-8 text-sm text-muted-foreground">Carico…</p>
}

export const routes: RouteObject[] = [
  { path: '/login', lazy: page(() => import('./auth'), (m) => m.LoginPage), HydrateFallback: Loading },
  {
    path: '/',
    element: <Layout areas={areas} />,
    HydrateFallback: Loading,
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
