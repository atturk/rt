import { Settings as SettingsIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router'

import { errorMessage } from '@/api/client'
import { useSettings, type Settings } from '@/api/settings'
import { LessonsRootSection, TelegramSection, TranscriptionSection } from '@/components/settings/general'
import { PricingSection, SecretsSection } from '@/components/settings/keys'
import { ConnectionsSection, NewConnectionSection, PhasesSection, RoutesSection } from '@/components/settings/models'
import { SetupWizard } from '@/components/settings/wizard'
import { Alert } from '@/components/ui/alert'
import { cn } from '@/lib/utils'
import type { Area } from './types'

export const SETUP_PATH = '/impostazioni/configurazione'

/** Primo avvio: finché la cartella dati non è impostata ogni pagina porta alla configurazione
 * guidata (le impostazioni restano raggiungibili). Mentre carica non blocca nulla. */
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
]

function SettingsLayout() {
  const settings = useSettings()
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight">Impostazioni</h1>
        <Link to={SETUP_PATH} className="text-xs text-muted-foreground underline-offset-4 hover:underline">
          Configurazione guidata
        </Link>
      </div>
      {settings.data?.setup_required && (
        <Alert tone="warning">
          La cartella dati non è ancora impostata. <Link to={SETUP_PATH} className="underline">Apri la configurazione guidata</Link>.
        </Alert>
      )}
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

const page = (render: (s: Settings) => ReactNode) => <WithSettings>{(s) => <div className="flex flex-col gap-4">{render(s)}</div>}</WithSettings>

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
              <LessonsRootSection settings={s} />
              <TranscriptionSection settings={s} />
              <TelegramSection settings={s} />
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
      ],
    },
  ],
  nav: [{ to: '/impostazioni', label: 'Impostazioni', icon: SettingsIcon }],
}
