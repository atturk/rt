import { Settings as SettingsIcon } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router'

import { errorMessage } from '@/api/client'
import { useSettings, type Settings } from '@/api/settings'
import { DataDirSection, TelegramSection, TranscriptionSection, WorkerSection } from '@/components/settings/general'
import { InfoSection } from '@/components/settings/info'
import { PricingSection, SecretsSection } from '@/components/settings/keys'
import { ConnectionsSection, DecisionModelSection, NewConnectionSection, PhasesSection, PromptEditorSection, RoutesSection } from '@/components/settings/models'
import { WebSearchSection } from '@/components/settings/websearch'
import { SetupWizard } from '@/components/settings/wizard'
import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import { Alert } from '@/components/ui/alert'
import { cn } from '@/lib/utils'
import type { Area } from './types'

export const SETUP_PATH = '/impostazioni/configurazione'

/** Se il backend segnala un passo obbligatorio mancante (setup_required) ogni pagina porta alla
 * configurazione guidata (le impostazioni restano raggiungibili). Mentre carica non blocca nulla. */
export function SetupGate() {
  const settings = useSettings()
  const location = useLocation()
  if (settings.data?.setup_required && !location.pathname.startsWith('/impostazioni')) {
    return <Navigate to={SETUP_PATH} replace />
  }
  return <Outlet />
}

/** Carica le impostazioni e passa i dati salvati alla pagina. */
function WithSettings({ children }: { children: (settings: Settings) => ReactNode }) {
  const settings = useSettings()
  if (settings.isPending) return <p className="text-sm text-muted-foreground">Carico le impostazioni…</p>
  if (settings.isError) return <Alert tone="danger">{errorMessage(settings.error)}</Alert>
  return <>{children(settings.data)}</>
}

const TABS = [
  { to: '/impostazioni', label: 'Generali', end: true },
  { to: '/impostazioni/modelli', label: 'Modelli' },
  { to: '/impostazioni/chiavi', label: 'Chiavi' },
  { to: '/impostazioni/costi', label: 'Costi' },
  { to: '/impostazioni/ricerca-web', label: 'Ricerca web' },
  { to: '/impostazioni/decisioni', label: 'Prompt e decisioni' },
  { to: '/impostazioni/info', label: 'Info' },
]

function SettingsLayout() {
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight">Impostazioni</h1>
        <Link to={SETUP_PATH} className="text-sm font-bold text-accent-foreground hover:underline">
          Configurazione guidata <span aria-hidden>→</span>
        </Link>
      </div>
      <nav aria-label="Sezioni delle impostazioni" className="flex gap-1 border-b">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn('-mb-px border-b-2 px-3 py-2 text-sm', isActive ? 'border-foreground font-semibold' : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </section>
  )
}

/** Link con ancora (es. /impostazioni#telegram dalla pagina Bot): scorre alla sezione quando è pronta. */
function ScrollToHash() {
  const { hash } = useLocation()
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: 'start' })
  }, [hash])
  return null
}

const page = (render: (s: Settings) => ReactNode) => (
  <WithSettings>
    {(s) => (
      <div className="flex flex-col gap-4">
        {render(s)}
        <ScrollToHash />
      </div>
    )}
  </WithSettings>
)

export const settingsArea: Area = {
  routes: [
    { path: 'impostazioni/configurazione', element: <WithSettings>{(s) => <SetupWizard settings={s} />}</WithSettings> },
    {
      path: 'impostazioni',
      element: <SettingsLayout />,
      children: [
        {
          index: true,
          element: page((s) => (
            <>
              <DataDirSection settings={s} />
              <WorkerSection settings={s} />
              <TranscriptionSection settings={s} />
              <TelegramSection settings={s} />
              <TelegramBotPanel />
            </>
          )),
        },
        {
          path: 'modelli',
          element: page((s) => (
            <>
              <PhasesSection settings={s} />
              <ConnectionsSection settings={s} />
              <NewConnectionSection />
              <RoutesSection settings={s} />
            </>
          )),
        },
        { path: 'chiavi', element: page((s) => <SecretsSection settings={s} />) },
        { path: 'costi', element: page((s) => <PricingSection settings={s} />) },
        { path: 'ricerca-web', element: page((s) => <WebSearchSection settings={s} />) },
        { path: 'decisioni', element: page(() => <><DecisionModelSection /><PromptEditorSection /></>) },
        { path: 'info', element: <InfoSection /> },
      ],
    },
  ],
  nav: [{ to: '/impostazioni', label: 'Impostazioni', icon: SettingsIcon }],
}
