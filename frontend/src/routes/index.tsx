import { Activity, Bot, Brain, ClipboardCheck, Images, LayoutDashboard, Settings as SettingsIcon, Upload } from 'lucide-react'
import { lazy, Suspense, type ComponentType } from 'react'
import type { RouteObject } from 'react-router'

import { JobsNavBadge } from '@/components/jobs/JobsIndicator'
import { Layout } from '@/components/Layout'
import { SetupGate } from './setupGate'
import type { Area } from './types'

/**
 * Le pagine di ogni area stanno in routes/<area>.tsx e si caricano solo quando servono (un
 * chunk per area, React.lazy): qui restano le rotte e le voci di menu, che servono subito.
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

const lessonsArea: Area = {
  routes: [
    { index: true, Component: page(lessons, (m) => m.DashboardPage) },
    { path: 'lezioni/:lessonId', Component: page(lessons, (m) => m.LessonPage) },
    { path: 'lezioni/:lessonId/rilevanza', Component: page(() => import('./relevance'), (m) => m.RelevancePage) },
  ],
  nav: [{ to: '/', label: 'Lezioni', icon: LayoutDashboard, end: true }],
}

const jobsArea: Area = {
  routes: [
    { path: 'importa', Component: page(jobs, (m) => m.ImportPage) },
    { path: 'job', Component: page(jobs, (m) => m.JobsPage) },
    { path: 'job/:jobId', Component: page(jobs, (m) => m.JobPage) },
    { path: 'lezioni/:lessonId/outline', Component: page(jobs, (m) => m.OutlinePage) },
  ],
  nav: [
    { to: '/importa', label: 'Importa', icon: Upload },
    { to: '/job', label: 'Job', icon: Activity, badge: JobsNavBadge },
  ],
}

const reviewsArea: Area = {
  routes: [{ path: 'review', Component: page(() => import('./reviews'), (m) => m.ReviewsPage) }],
  nav: [{ to: '/review', label: 'Review', icon: ClipboardCheck }],
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
  nav: [{ to: '/recall', label: 'Recall', icon: Brain }],
}

const imagesArea: Area = {
  routes: [
    { path: 'arricchimento', Component: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/arricchimento', Component: page(images, (m) => m.ImagesPage) },
    { path: 'immagini', Component: page(images, (m) => m.ImagesIndex) },
    { path: 'lezioni/:lessonId/immagini', Component: page(images, (m) => m.ImagesPage) },
  ],
  nav: [{ to: '/arricchimento', label: 'Arricchimento', icon: Images }],
}

/** Il pannello di avvio sta anche nelle impostazioni (RT4-F5); qui la pagina completa (RT4-FA6). */
const telegramArea: Area = {
  routes: [{ path: 'bot', Component: page(() => import('./telegram'), (m) => m.TelegramPage) }],
  nav: [{ to: '/bot', label: 'Bot Telegram', icon: Bot }],
}

const settingsArea: Area = {
  routes: [
    { path: 'impostazioni/configurazione', Component: page(settings, (m) => m.SetupWizardPage) },
    {
      path: 'impostazioni',
      Component: page(settings, (m) => m.SettingsLayout),
      children: [
        { index: true, Component: page(settings, (m) => m.GeneralSettingsPage) },
        { path: 'modelli', Component: page(settings, (m) => m.ModelsSettingsPage) },
        { path: 'chiavi', Component: page(settings, (m) => m.KeysSettingsPage) },
        { path: 'costi', Component: page(settings, (m) => m.CostsSettingsPage) },
        { path: 'ricerca-web', Component: page(settings, (m) => m.WebSearchSettingsPage) },
        { path: 'decisioni', Component: page(settings, (m) => m.DecisionsSettingsPage) },
        { path: 'info', Component: page(settings, (m) => m.InfoSettingsPage) },
      ],
    },
  ],
  nav: [{ to: '/impostazioni', label: 'Impostazioni', icon: SettingsIcon }],
}

export const areas: Area[] = [lessonsArea, jobsArea, reviewsArea, reviewArea, recallArea, imagesArea, telegramArea, settingsArea]

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
    element: <Layout areas={areas} />,
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
