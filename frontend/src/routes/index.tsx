import { lazy, Suspense, type ComponentType } from 'react'
import { Navigate, Outlet, useLocation, useParams, type RouteObject } from 'react-router'

import { Layout } from '@/components/Layout'
import { SETTINGS_REDIRECTS } from '@/lib/settings'
import { useTheme } from '@/lib/theme'
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
const settings = () => import('./settings')

const bare = { bare: true }

function SettingsLegacyRedirect({ section }: { section: string }) {
  const { search, hash } = useLocation()
  return <Navigate to={`/impostazioni/${section}${search}${hash}`} replace />
}

function PersonalPreferences() {
  useTheme()
  return <Outlet />
}

function RedirectSubjectRecall() {
  const { materia } = useParams()
  return <Navigate to={materia ? `/?materia=${encodeURIComponent(materia)}` : '/'} replace />
}

/** Le pagine tolte della lezione aprono il pannello corrispondente; restano gli altri parametri (es. ?issue=). */
function RedirectLessonPanel({ panel }: { panel: string }) {
  const { lessonId } = useParams()
  const { search, hash } = useLocation()
  const query = new URLSearchParams(search)
  query.set('panel', panel)
  return <Navigate to={`/lezioni/${lessonId}?${query}${hash}`} replace />
}

function RedirectLesson() {
  const { lessonId } = useParams()
  const { search, hash } = useLocation()
  return <Navigate to={`/lezioni/${lessonId}${search}${hash}`} replace />
}

const lessonsArea: Area = {
  routes: [
    { index: true, Component: page(lessons, (m) => m.DashboardPage), handle: bare },
    { path: 'lezioni', element: <Navigate to="/" replace /> },
    { path: 'lezioni/nuova/:jobId', Component: page(lessons, (m) => m.NewLessonPage), handle: bare },
    { path: 'lezioni/:lessonId', Component: page(lessons, (m) => m.LessonPage), handle: bare },
    { path: 'lezioni/:lessonId/rilevanza', element: <RedirectLessonPanel panel="classificatore" /> },
    { path: 'lezioni/:lessonId/relevance', element: <RedirectLessonPanel panel="classificatore" /> },
  ],
}

const jobsArea: Area = {
  routes: [
    { path: 'importa', element: <Navigate to="/" replace /> },
    { path: 'job', Component: page(jobs, (m) => m.JobsPage), handle: bare },
    { path: 'job/:jobId', Component: page(jobs, (m) => m.JobPage), handle: bare },
    { path: 'lezioni/:lessonId/outline', element: <RedirectLesson /> },
  ],
}

// Studio (design 4.2, schermate 05 e 06): dalle righe di Lezioni e dalla lezione.
const study = () => import('./study')
const studyArea: Area = {
  routes: [
    { path: 'studio/lezione/:lessonId', Component: page(study, (m) => m.StudyLessonPage), handle: bare },
  ],
}

const reviewsArea: Area = {
  routes: [{ path: 'review', element: <Navigate to="/" replace /> }],
}

const reviewArea: Area = {
  routes: [{ path: 'lezioni/:lessonId/revisione', element: <RedirectLessonPanel panel="verifica" /> }],
}

const recallArea: Area = {
  routes: [
    { path: 'recall', element: <Navigate to="/" replace /> },
    { path: 'recall/materie', element: <Navigate to="/" replace /> },
    { path: 'recall/materie/:materia', element: <RedirectSubjectRecall /> },
    { path: 'recall/giorno', element: <Navigate to="/" replace /> },
    { path: 'recall/giorno/:day', element: <Navigate to="/" replace /> },
    { path: 'recall/selezione/:ids', Component: page(recall, (m) => m.LightweightSession), handle: bare },
    { path: 'lezioni/:lessonId/recall', Component: page(recall, (m) => m.LightweightSession), handle: bare },
    { path: 'lezioni/:lessonId/sessione', Component: page(recall, (m) => m.LightweightSession), handle: bare },
    { path: 'lezioni/:lessonId/recall/domande', element: <RedirectLessonPanel panel="domande" /> },
  ],
}

const imagesArea: Area = {
  routes: [
    { path: 'arricchimento', element: <Navigate to="/" replace /> },
    { path: 'lezioni/:lessonId/arricchimento', element: <RedirectLessonPanel panel="arricchimento" /> },
    { path: 'immagini', element: <Navigate to="/" replace /> },
    { path: 'lezioni/:lessonId/immagini', element: <RedirectLessonPanel panel="arricchimento" /> },
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
        { index: true, Component: page(settings, (m) => m.SettingsIndexPage) },
        { path: 'aspetto', Component: page(settings, (m) => m.AppearanceSettingsPage) },
        { path: 'editor', Component: page(settings, (m) => m.EditorSettingsPage) },
        { path: 'lavorazione', Component: page(settings, (m) => m.ProcessingSettingsPage) },
        { path: 'modelli-connessioni', Component: page(settings, (m) => m.ModelsSettingsPage) },
        { path: 'telegram', Component: page(settings, (m) => m.TelegramSettingsPage) },
        { path: 'accesso', Component: page(settings, (m) => m.DeviceSettingsPage) },
        { path: 'info-aggiornamenti', Component: page(settings, (m) => m.InfoSettingsPage) },
        ...Object.entries(SETTINGS_REDIRECTS).map(([path, section]) => ({ path, element: <SettingsLegacyRedirect section={section} /> })),
      ],
    },
    { path: 'bot', element: <SettingsLegacyRedirect section="telegram" /> },
    ...Object.entries({ chiavi: 'modelli-connessioni', costi: 'modelli-connessioni', 'ricerca-web': 'lavorazione', decisioni: 'modelli-connessioni', info: 'info-aggiornamenti' }).map(([path, section]) => ({ path, element: <SettingsLegacyRedirect section={section} /> })),
  ],
}

export const areas: Area[] = [lessonsArea, studyArea, jobsArea, reviewsArea, reviewArea, recallArea, imagesArea, settingsArea]

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
    children: [{ element: <PersonalPreferences />, children: [{ element: <SetupGate />, children: areas.flatMap((a) => a.routes) }] }],
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
