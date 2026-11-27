import { useReturnAddress } from '@/lib/returnAddress'
import { useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  CalendarDays,
  ChevronRight,
  CircleHelp,
  Heart,
  Info,
  Keyboard,
  LogOut,
  Palette,
  Send,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Wand2,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { api, errorMessage } from '@/api/client'
import { useLogout } from '@/api/hooks'
import { useSettings, useSystemInfo, type Settings } from '@/api/settings'
import { DeviceAccessSection } from '@/components/settings/device-access'
import { CloseActionSection, StartAtLoginSection, TranscriptionSection } from '@/components/settings/general'
import { NotificationsCard, TelegramSection } from '@/components/settings/telegram'
import { InfoSection } from '@/components/settings/info'
import { ConnectionsSection, DecisionModelSection, NewConnectionSection, PhasesSection, PromptEditorSection, RoutesSection } from '@/components/settings/models'
import { AppearanceSection, OutlineSettingsSection, SourceDefaultsSection, SpeedSection } from '@/components/settings/preferences'
import { WebSearchSection } from '@/components/settings/websearch'
import { ClassifierSettingsSection } from '@/components/settings/classifier'
import { EnrichmentSettingsSection } from '@/components/settings/enrichment'
import { QuestionsSettingsSection } from '@/components/settings/questions'
import { SubjectsCalendarSection } from '@/components/settings/subjects'
import { EditorShortcutsSection } from '@/components/settings/shortcuts'
import { SetupWizard } from '@/components/settings/wizard'
import { CloudSection } from '@/components/settings/cloud'
import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { Alert } from '@/components/ui/alert'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { useIsPhone } from '@/lib/phone'
import { cn } from '@/lib/utils'
import { SettingsDisclosure, SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/ui'
import { SETUP_PATH } from './setupGate'

export { SETUP_PATH, SetupGate } from './setupGate'

export { SETTINGS_SECTIONS, SETTINGS_REDIRECTS } from '@/lib/settings'
import { SETTINGS_SECTIONS } from '@/lib/settings'

const SECTION_ICONS: Record<(typeof SETTINGS_SECTIONS)[number]['path'], LucideIcon> = {
  aspetto: Palette,
  domande: CircleHelp,
  'materie-calendario': CalendarDays,
  editor: Keyboard,
  lavorazione: SlidersHorizontal,
  'modelli-connessioni': Sparkles,
  telegram: Send,
  accesso: Smartphone,
  'info-aggiornamenti': Info,
}

export function SettingsRedirect({ section }: { section: string }) {
  const { search, hash, state } = useLocation()
  return <Navigate to={`/impostazioni/${section}${search}${hash}`} state={state} replace />
}

function WithSettings({ children }: { children: (settings: Settings) => ReactNode }) {
  const settings = useSettings()
  if (settings.isPending) return <p className="text-body text-muted-foreground">Carico le impostazioni…</p>
  if (settings.isError) return <Alert tone="danger">{errorMessage(settings.error)}</Alert>
  return <>{children(settings.data)}</>
}

export function SettingsLayout() {
  const returnAddress = useReturnAddress()
  const phone = useIsPhone()
  const { pathname, hash } = useLocation()
  const index = pathname === '/impostazioni'
  const targets: Record<string, string> = { telegram: 'telegram', cartella: 'info-aggiornamenti', 'job-paralleli': 'lavorazione', trascrizione: 'lavorazione', preferenze: 'aspetto' }
  if (index && targets[hash.slice(1)]) return <SettingsRedirect section={targets[hash.slice(1)]} />
  const isSupport = pathname === '/impostazioni/supporta'
  const current = SETTINGS_SECTIONS.find(s => pathname === `/impostazioni/${s.path}`) ?? SETTINGS_SECTIONS[0]
  const sectionLabel = isSupport ? 'Supporta RT' : current.label
  return <>
    <PageHeader title={phone && !index ? sectionLabel : 'Impostazioni'} back={phone && !index ? { to: '/impostazioni', label: 'Impostazioni' } : { to: returnAddress, label: 'Indietro' }} />
    <PageBody className="md:px-5">
      <div className="flex min-w-0 gap-8">
        {(!phone || index) && <nav aria-label="Sezioni delle impostazioni" className={cn('shrink-0', phone ? 'w-full' : 'sticky top-20 h-fit max-h-[calc(100vh-6rem)] w-64 overflow-y-auto flex flex-col gap-0.5')}>
          {SETTINGS_SECTIONS.map((s) => {
            const Icon = SECTION_ICONS[s.path]
            return (
              <NavLink
                key={s.path}
                to={`/impostazioni/${s.path}`}
                className={({ isActive }) =>
                  cn(
                    'flex items-center justify-between gap-2.5 rounded-lg px-3 py-2.5 text-body transition-colors',
                    phone ? 'border-b py-3' : '',
                    (isActive || (!phone && index && s.path === 'aspetto'))
                      ? 'bg-muted font-medium text-foreground'
                      : 'text-foreground/80 hover:bg-muted/60 hover:text-foreground',
                  )
                }
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0">
                    {s.label}
                    {phone && <span className="mt-1 block text-meta font-normal text-muted-foreground">{s.description}</span>}
                  </span>
                </span>
                {phone && <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
              </NavLink>
            )
          })}
          <Link
            to="/guida"
            className={cn(
              'flex items-center justify-between gap-2.5 rounded-lg px-3 py-2.5 text-body text-foreground/80 transition-colors hover:bg-muted/60 hover:text-foreground',
              phone ? 'border-b py-3' : '',
            )}
          >
            <span className="flex min-w-0 items-center gap-2.5">
              <BookOpen className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0">
                Guida
                {phone && <span className="mt-1 block text-meta font-normal text-muted-foreground">Manuale e argomenti</span>}
              </span>
            </span>
            {phone && <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
          </Link>
          <SupportButton />
        </nav>}
        {(!phone || !index) && <div className="min-w-0 flex-1">
          {!phone && isSupport && <h2 className="mb-4 text-heading font-semibold">{sectionLabel}</h2>}<Outlet />
        </div>}
      </div>
    </PageBody>
  </>
}

/** «Supporta RT» sotto Guida, solo se c'è un URL per le donazioni: apre la pagina interna
 * (/impostazioni/supporta) dove si trova il collegamento a Ko-fi. Blu fisso con testo bianco:
 * contrasto uguale in tema chiaro e scuro. */
function SupportButton() {
  const url = useSystemInfo().data?.donazioni_url
  if (!url) return null
  return <NavLink to="/impostazioni/supporta" data-testid="link-sostieni-rt"
    className={({ isActive }) => cn(
      'mt-4 flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2.5 text-body font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-300',
      isActive && 'ring-2 ring-inset ring-blue-300',
    )}>
    <Heart className="size-4 shrink-0 fill-current" aria-hidden />
    Supporta RT
  </NavLink>
}

export function SupportSettingsPage() {
  const queryClient = useQueryClient()
  const url = useSystemInfo().data?.donazioni_url ?? ''
  const [thanked, setThanked] = useState(false)
  const sendEvent = (event: 'donated' | 'already_donated') => {
    queryClient.setQueryData(['support-prompt'], (old: { visible?: boolean; url?: string } | undefined) => ({
      url: old?.url ?? url,
      visible: false,
    }))
    void api.POST('/api/v1/system/support-prompt', { body: { event } }).catch(() => {})
  }
  const handleDonateClick = () => sendEvent('donated')
  const handleAlreadyDonated = () => {
    sendEvent('already_donated')
    setThanked(true)
  }
  return (
    <section className="max-w-[52ch] space-y-4">
      <div className="flex size-11 items-center justify-center rounded-[11px] bg-blue-600 text-white shadow-sm" aria-hidden>
        <Heart className="size-[22px] fill-current" />
      </div>
      <h3 className="text-heading font-semibold">RT è fatto da uno studente, per gli studenti</h3>
      <p className="text-body text-foreground">
        RT è gratuito e senza abbonamenti: usi le tue chiavi e paghi solo quello che consumi dal provider. Lo sviluppo va avanti grazie alle donazioni.
      </p>
      <p className="text-body text-foreground">
        Se RT ti fa risparmiare tempo, una donazione aiuta a tenerlo vivo.
      </p>
      {url && (
        <div className="space-y-2 pt-2">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleDonateClick}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-body font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <Heart className="size-4 shrink-0 fill-current" aria-hidden />
            Dona con Ko-fi
          </a>
          <p className="text-meta text-muted-foreground">Si apre nel browser: carta o PayPal.</p>
          {thanked ? (
            <p className="pt-2 text-meta text-muted-foreground" role="status" data-testid="support-thanks">Grazie!</p>
          ) : (
            <button
              type="button"
              onClick={handleAlreadyDonated}
              data-testid="support-already-donated"
              className="pt-2 text-meta text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Ho già donato
            </button>
          )}
        </div>
      )}
    </section>
  )
}

function ScrollToHash() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    const id = decodeURIComponent(hash.slice(1))
    window.dispatchEvent(new CustomEvent('rt-settings-reveal', { detail: { id } }))
    const target = document.getElementById(id)
    for (let parent = target?.parentElement; parent; parent = parent.parentElement) {
      if (parent instanceof HTMLDetailsElement) parent.open = true
    }
    target?.scrollIntoView({ block: 'start' })
  }, [hash])
  return null
}

export function SettingsIndexPage() {
  const { hash } = useLocation()
  const targets: Record<string, string> = { telegram: 'telegram', cartella: 'info-aggiornamenti', 'job-paralleli': 'lavorazione', trascrizione: 'lavorazione', preferenze: 'aspetto' }
  if (targets[hash.slice(1)]) return <SettingsRedirect section={targets[hash.slice(1)]} />
  return <AppearanceSettingsPage />
}
export function SetupWizardPage() { return <WithSettings>{s => <SetupWizard settings={s} />}</WithSettings> }
export function AppearanceSettingsPage() {
  return (
    <WithSettings>
      {(s) => (
        <SettingsPage title="Aspetto e lettura" description="Tema, testo dello Studio, copia, lettura veloce e comportamento della finestra.">
          <AppearanceSection settings={s} />
          <StartAtLoginSection settings={s} />
          <CloseActionSection settings={s} />
          <ScrollToHash />
        </SettingsPage>
      )}
    </WithSettings>
  )
}
export function QuestionsSettingsPage() { return <QuestionsSettingsSection /> }
export function SubjectsCalendarSettingsPage() { return <SubjectsCalendarSection /> }
export function EditorSettingsPage() { return <EditorShortcutsSection /> }
export function ProcessingSettingsPage() {
  return (
    <WithSettings>
      {(s) => (
        <SettingsPage
          title="Lavorazione delle lezioni"
          description="Trascrizione, scaletta, fonti predefinite, arricchimento, ricerca web e parallelismo."
        >
          <TranscriptionSection settings={s} />
          <OutlineSettingsSection settings={s} />
          <SourceDefaultsSection />
          <EnrichmentSettingsSection settings={s} />
          <WebSearchSection settings={s} />
          <SpeedSection settings={s} />
          <ScrollToHash />
        </SettingsPage>
      )}
    </WithSettings>
  )
}
export function ModelsSettingsPage() {
  return (
    <WithSettings>
      {(s) => (
        <SettingsPage title="Modelli e connessioni" description="Modelli per fase, provider, chiavi API e stima dei costi.">
          <CloudSection />
          <PhasesSection settings={s} />
          <ConnectionsSection settings={s} />
          <NewConnectionSection />
          <SettingsGroup id="avanzate" title="Avanzate" description="Routing secondario, classificatore e aggiunte ai prompt.">
            <SettingsDisclosure id="route" label="Route avanzate" summary="Primaria e secondaria">
              <RoutesSection settings={s} />
            </SettingsDisclosure>
            <SettingsDisclosure id="modelli-decisionali" label="Modelli decisionali" summary="Classificatore e mappature">
              <div className="flex flex-col gap-6">
                <ClassifierSettingsSection />
                <DecisionModelSection />
              </div>
            </SettingsDisclosure>
            <SettingsDisclosure id="prompt" label="Istruzioni dei prompt" summary="Aggiunte ai prompt">
              <PromptEditorSection />
            </SettingsDisclosure>
          </SettingsGroup>
          <ScrollToHash />
        </SettingsPage>
      )}
    </WithSettings>
  )
}
export function TelegramSettingsPage() {
  return (
    <WithSettings>
      {(s) => (
        <SettingsPage title="Telegram" description="Notifiche nella tua chat personale quando una lezione è pronta o serve una tua decisione.">
          <TelegramSection settings={s} />
          {s.telegram.enabled && <NotificationsCard />}
          <ScrollToHash />
        </SettingsPage>
      )}
    </WithSettings>
  )
}
export function DeviceSettingsPage() { return <DeviceAccessSection /> }
function InfoActions() {
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <SettingsGroup title="Sessione e configurazione">
      <SettingsRow
        label="Configurazione guidata"
        description="Rivedi connessioni, modelli e Telegram passo passo."
        compactControl
        control={<IconLink to={SETUP_PATH} label="Configurazione guidata" icon={Wand2} />}
      />
      <SettingsRow
        label="Esci dall'account"
        compactControl
        control={<IconButton label="Esci" icon={LogOut} disabled={logout.isPending} onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })} />}
      />
    </SettingsGroup>
  )
}
export function InfoSettingsPage() {
  return (
    <SettingsPage title="Info e aggiornamenti" description="Versione di RT, aggiornamenti, novità, spazio su disco e sessione.">
      <InfoSection />
      <InfoActions />
    </SettingsPage>
  )
}
export { UpdatePopup } from '@/components/settings/UpdatePopup'

