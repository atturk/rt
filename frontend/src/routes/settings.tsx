import { ChevronRight, LogOut, Wand2 } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLogout } from '@/api/hooks'
import { useSettings, type Settings } from '@/api/settings'
import { DeviceAccessSection } from '@/components/settings/device-access'
import { TelegramSection, TranscriptionSection, WorkerSection } from '@/components/settings/general'
import { InfoSection } from '@/components/settings/info'
import { ConnectionsSection, DecisionModelSection, NewConnectionSection, PhasesSection, PromptEditorSection, RoutesSection } from '@/components/settings/models'
import { AppearanceSection, OutlineSettingsSection } from '@/components/settings/preferences'
import { WebSearchSection } from '@/components/settings/websearch'
import { EnrichmentSettingsSection } from '@/components/settings/enrichment'
import { SetupWizard } from '@/components/settings/wizard'
import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { Alert } from '@/components/ui/alert'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { useIsPhone } from '@/lib/phone'
import { cn } from '@/lib/utils'
import { NotificationsCard, TelegramUserPanel } from './telegram'
import { SETUP_PATH } from './setupGate'

export { SETUP_PATH, SetupGate } from './setupGate'

export { SETTINGS_SECTIONS, SETTINGS_REDIRECTS } from '@/lib/settings'
import { SETTINGS_SECTIONS } from '@/lib/settings'

export function SettingsRedirect({ section }: { section: string }) {
  const { search, hash } = useLocation()
  return <Navigate to={`/impostazioni/${section}${search}${hash}`} replace />
}

function WithSettings({ children }: { children: (settings: Settings) => ReactNode }) {
  const settings = useSettings()
  if (settings.isPending) return <p className="text-body text-muted-foreground">Carico le impostazioni…</p>
  if (settings.isError) return <Alert tone="danger">{errorMessage(settings.error)}</Alert>
  return <>{children(settings.data)}</>
}

export function SettingsLayout() {
  const phone = useIsPhone()
  const { pathname, hash } = useLocation()
  const index = pathname === '/impostazioni'
  const targets: Record<string, string> = { telegram: 'telegram', cartella: 'info-aggiornamenti', 'job-paralleli': 'lavorazione', trascrizione: 'lavorazione', preferenze: 'aspetto' }
  if (index && targets[hash.slice(1)]) return <SettingsRedirect section={targets[hash.slice(1)]} />
  const current = SETTINGS_SECTIONS.find(s => pathname === `/impostazioni/${s.path}`) ?? SETTINGS_SECTIONS[0]
  return <>
    <PageHeader title={phone && !index ? current.label : 'Impostazioni'} back={phone && !index ? { to: '/impostazioni', label: 'Impostazioni' } : undefined} />
    <PageBody className="md:px-5">
      <div className="flex min-w-0 gap-8">
        {(!phone || index) && <nav aria-label="Sezioni delle impostazioni" className={cn('shrink-0', phone ? 'w-full' : 'sticky top-20 h-fit w-60')}>
          {SETTINGS_SECTIONS.map(s => <NavLink key={s.path} to={`/impostazioni/${s.path}`}
            className={({ isActive }) => cn('flex items-center justify-between gap-2 rounded-lg px-3 py-3 text-body',
              phone ? 'border-b' : '', (isActive || (!phone && index && s.path === 'aspetto')) ? 'bg-muted font-semibold' : 'hover:bg-muted')}>
            <span>{s.label}{phone && <span className="mt-1 block text-meta font-normal text-muted-foreground">{s.description}</span>}</span>
            {phone && <ChevronRight className="size-4 shrink-0" aria-hidden />}
          </NavLink>)}
        </nav>}
        {(!phone || !index) && <div className="min-w-0 flex-1">
          {!phone && <h2 className="mb-4 text-heading font-semibold">{current.label}</h2>}<Outlet />
        </div>}
      </div>
    </PageBody>
  </>
}

function ScrollToHash() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    const target = document.getElementById(decodeURIComponent(hash.slice(1)))
    for (let parent = target?.parentElement; parent; parent = parent.parentElement) {
      if (parent instanceof HTMLDetailsElement) parent.open = true
    }
    target?.scrollIntoView({ block: 'start' })
  }, [hash])
  return null
}
const page = (render: (settings: Settings) => ReactNode) => <WithSettings>{s => <div className="flex flex-col divide-y">{render(s)}<ScrollToHash /></div>}</WithSettings>

export function SettingsIndexPage() {
  const { hash } = useLocation()
  const targets: Record<string, string> = { telegram: 'telegram', cartella: 'info-aggiornamenti', 'job-paralleli': 'lavorazione', trascrizione: 'lavorazione', preferenze: 'aspetto' }
  if (targets[hash.slice(1)]) return <SettingsRedirect section={targets[hash.slice(1)]} />
  return <AppearanceSettingsPage />
}
export function SetupWizardPage() { return <WithSettings>{s => <SetupWizard settings={s} />}</WithSettings> }
export function AppearanceSettingsPage() { return page(s => <AppearanceSection settings={s} />) }
export function EditorSettingsPage() { return <p className="text-body">Scorciatoie dell’editor</p> }
export function ProcessingSettingsPage() {
  return page(s => <><TranscriptionSection settings={s} /><OutlineSettingsSection settings={s} /><EnrichmentSettingsSection settings={s} /><WebSearchSection settings={s} /><WorkerSection settings={s} /></>)
}
export function ModelsSettingsPage() {
  return page(s => <><PhasesSection settings={s} /><ConnectionsSection settings={s} /><NewConnectionSection />
    <details id="avanzate" className="py-4" open={undefined}><summary className="cursor-pointer text-body font-semibold">Avanzate</summary>
      <RoutesSection settings={s} />
      <details id="modelli-decisionali" className="py-3"><summary className="cursor-pointer text-body">Modelli decisionali</summary><DecisionModelSection /><EnrichmentSettingsSection settings={s} decisions /></details>
      <PromptEditorSection />
    </details></>)
}
export function TelegramSettingsPage() {
  return page(s => <><TelegramSection settings={s} />{s.telegram.enabled && <><TelegramBotPanel /><TelegramUserPanel /><NotificationsCard /></>}</>)
}
export function DeviceSettingsPage() { return <DeviceAccessSection /> }
function InfoActions() {
  const logout = useLogout()
  const navigate = useNavigate()
  return <div className="flex items-center gap-3 py-4 text-body"><IconLink to={SETUP_PATH} label="Configurazione guidata" icon={Wand2} /><span className="mr-auto">Configurazione guidata</span>
    <IconButton label="Esci" icon={LogOut} disabled={logout.isPending} onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })} />
  </div>
}
export function InfoSettingsPage() { return <><InfoSection /><InfoActions /></> }
