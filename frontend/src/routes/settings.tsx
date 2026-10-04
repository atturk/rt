import { LogOut, Moon, Sun, Wand2 } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLogout } from '@/api/hooks'
import { useSettings, type Settings } from '@/api/settings'
import { DeviceAccessSection } from '@/components/settings/device-access'
import { DataDirSection, TelegramSection, TranscriptionSection, WorkerSection } from '@/components/settings/general'
import { InfoSection } from '@/components/settings/info'
import { PricingSection, SecretsSection } from '@/components/settings/keys'
import { ConnectionsSection, DecisionModelSection, NewConnectionSection, PhasesSection, PromptEditorSection, RoutesSection } from '@/components/settings/models'
import { PreferencesSection } from '@/components/settings/preferences'
import { WebSearchSection } from '@/components/settings/websearch'
import { EnrichmentSettingsSection } from '@/components/settings/enrichment'
import { SetupWizard } from '@/components/settings/wizard'
import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { Alert } from '@/components/ui/alert'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { SETUP_PATH } from './setupGate'

export { SETUP_PATH, SetupGate } from './setupGate'

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
  { to: '/impostazioni/bot', label: 'Bot Telegram' },
  { to: '/impostazioni/info', label: 'Info' },
]

/** Tema e uscita: nel design 4.2 non stanno nel menu, ma nell'intestazione delle impostazioni. */
function SettingsActions() {
  const [theme, toggleTheme] = useTheme()
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <>
      <IconLink to={SETUP_PATH} label="Configurazione guidata" icon={Wand2} />
      <IconButton label={theme === 'dark' ? 'Tema chiaro' : 'Tema scuro'} icon={theme === 'dark' ? Sun : Moon} onClick={toggleTheme} />
      <IconButton
        label="Esci"
        icon={LogOut}
        disabled={logout.isPending}
        onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })}
      />
    </>
  )
}

export function SettingsLayout() {
  return (
    <>
      <PageHeader title="Impostazioni" actions={<SettingsActions />} />
      <PageBody>
    <section className="flex flex-col gap-5">
      <nav aria-label="Sezioni delle impostazioni" className="flex gap-1 overflow-x-auto border-b">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn('-mb-px shrink-0 border-b-2 px-3 py-2 text-sm', isActive ? 'border-foreground font-semibold' : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </section>
      </PageBody>
    </>
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

export function SetupWizardPage() {
  return <WithSettings>{(s) => <SetupWizard settings={s} />}</WithSettings>
}

export function GeneralSettingsPage() {
  return page((s) => (
    <>
      <PreferencesSection settings={s} />
      <DataDirSection settings={s} />
      <WorkerSection settings={s} />
      <TranscriptionSection settings={s} />
      <TelegramSection settings={s} />
      <TelegramBotPanel />
      <DeviceAccessSection />
    </>
  ))
}

export function ModelsSettingsPage() {
  return page((s) => (
    <>
      <PhasesSection settings={s} />
      <EnrichmentSettingsSection />
      <ConnectionsSection settings={s} />
      <NewConnectionSection />
      <RoutesSection settings={s} />
    </>
  ))
}

export const KeysSettingsPage = () => page((s) => <SecretsSection settings={s} />)
export const CostsSettingsPage = () => page((s) => <PricingSection settings={s} />)
export const WebSearchSettingsPage = () => page((s) => <WebSearchSection settings={s} />)
export const DecisionsSettingsPage = () => page(() => <><DecisionModelSection /><PromptEditorSection /></>)
export { InfoSection as InfoSettingsPage }
